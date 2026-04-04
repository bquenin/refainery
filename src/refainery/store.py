"""SQLite cache/index layer for extracted invocations and analysis results.

Provides incremental extraction (only re-parse changed conversations) and
indexed querying for filtering by provider, skill, time range, etc.

DB location: ~/.local/state/refainery/refainery.db
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from refainery.models import AnalysisResult, ConversationRef, FailureCluster, ToolInvocation

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT NOT NULL,
    provider        TEXT NOT NULL,
    path            TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    project_path    TEXT,
    indexed_at      TEXT NOT NULL,
    PRIMARY KEY (conversation_id, provider)
);

CREATE TABLE IF NOT EXISTS invocations (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id      TEXT NOT NULL,
    provider             TEXT NOT NULL,
    timestamp            TEXT NOT NULL,
    tool_name            TEXT NOT NULL,
    command              TEXT,
    arguments            TEXT NOT NULL,
    output               TEXT NOT NULL,
    success              INTEGER NOT NULL,
    next_action          TEXT,
    skill_context        TEXT,
    conversation_summary TEXT
);

CREATE INDEX IF NOT EXISTS idx_inv_conv ON invocations (conversation_id, provider);
CREATE INDEX IF NOT EXISTS idx_inv_provider ON invocations (provider);
CREATE INDEX IF NOT EXISTS idx_inv_skill ON invocations (skill_context);
CREATE INDEX IF NOT EXISTS idx_inv_timestamp ON invocations (timestamp);
CREATE INDEX IF NOT EXISTS idx_inv_success ON invocations (success);
CREATE INDEX IF NOT EXISTS idx_inv_tool ON invocations (tool_name);

CREATE TABLE IF NOT EXISTS analysis_results (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    skill               TEXT NOT NULL,
    tool                TEXT NOT NULL,
    failure_type        TEXT NOT NULL,
    frequency           INTEGER NOT NULL,
    providers           TEXT NOT NULL,
    root_cause          TEXT NOT NULL,
    severity            TEXT NOT NULL,
    skill_md_suggestion TEXT,
    cli_tool_suggestion TEXT,
    explanation         TEXT NOT NULL,
    analyzed_at         TEXT NOT NULL,
    UNIQUE (skill, tool, failure_type)
);

CREATE TABLE IF NOT EXISTS analysis_sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL UNIQUE,
    skill        TEXT NOT NULL,
    tool         TEXT NOT NULL,
    failure_type TEXT NOT NULL,
    frequency    INTEGER NOT NULL,
    providers    TEXT NOT NULL,
    analysis     TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    resolved     INTEGER NOT NULL DEFAULT 0,
    first_seen   TEXT,
    last_seen    TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_skill ON analysis_sessions (skill);
"""


def _default_db_path() -> Path:
    return Path.home() / ".local" / "state" / "refainery" / "refainery.db"


class Store:
    """SQLite-backed cache for invocations and analysis results."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()
        self._conn.executescript(_SCHEMA)

    def _migrate(self) -> None:
        """Handle schema migrations from older DB versions."""
        # Check if conversations table exists with old 'mtime' column
        try:
            cols = {row[1] for row in self._conn.execute("PRAGMA table_info(conversations)").fetchall()}
        except sqlite3.Error:
            return  # Table doesn't exist yet, _SCHEMA will create it
        if "mtime" in cols and "content_hash" not in cols:
            self._conn.executescript("DROP TABLE IF EXISTS conversations; DROP TABLE IF EXISTS invocations;")
            self._conn.commit()

        # Add columns to analysis_sessions if missing
        try:
            session_cols = {row[1] for row in self._conn.execute("PRAGMA table_info(analysis_sessions)").fetchall()}
        except sqlite3.Error:
            return
        if session_cols:
            if "resolved" not in session_cols:
                self._conn.execute("ALTER TABLE analysis_sessions ADD COLUMN resolved INTEGER NOT NULL DEFAULT 0")
            if "first_seen" not in session_cols:
                self._conn.execute("ALTER TABLE analysis_sessions ADD COLUMN first_seen TEXT")
            if "last_seen" not in session_cols:
                self._conn.execute("ALTER TABLE analysis_sessions ADD COLUMN last_seen TEXT")
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # --- Conversation watermark tracking ---

    def get_content_hash(self, conversation_id: str, provider: str) -> str | None:
        """Return the stored content_hash for a conversation, or None if not indexed."""
        row = self._conn.execute(
            "SELECT content_hash FROM conversations WHERE conversation_id = ? AND provider = ?",
            (conversation_id, provider),
        ).fetchone()
        return row[0] if row else None

    def needs_reindex(self, conv: ConversationRef) -> bool:
        """Check if a conversation needs (re)indexing.

        Compares content_hash (file mtime+size for Claude, bubble count for Cursor)
        which is stable across runs unlike Cursor's shifting timestamps.
        """
        stored = self.get_content_hash(conv.conversation_id, conv.provider)
        if stored is None:
            return True
        return conv.content_hash != stored

    def mark_indexed(self, conv: ConversationRef) -> None:
        """Record that a conversation has been indexed with its current content_hash."""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT OR REPLACE INTO conversations (conversation_id, provider, path, content_hash, project_path, indexed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (conv.conversation_id, conv.provider, conv.path, conv.content_hash or "", conv.project_path, now),
        )

    # --- Invocation storage ---

    def delete_invocations(self, conversation_id: str, provider: str) -> None:
        """Remove all invocations for a conversation (before re-indexing)."""
        self._conn.execute(
            "DELETE FROM invocations WHERE conversation_id = ? AND provider = ?",
            (conversation_id, provider),
        )

    def insert_invocations(self, invocations: list[ToolInvocation]) -> None:
        """Bulk-insert invocations."""
        self._conn.executemany(
            "INSERT INTO invocations "
            "(conversation_id, provider, timestamp, tool_name, command, arguments, output, success, next_action, skill_context, conversation_summary) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    inv.conversation_id,
                    inv.provider,
                    inv.timestamp.isoformat(),
                    inv.tool_name,
                    inv.command,
                    json.dumps(inv.arguments),
                    inv.output,
                    int(inv.success),
                    inv.next_action,
                    inv.skill_context,
                    inv.conversation_summary,
                )
                for inv in invocations
            ],
        )

    def commit(self) -> None:
        self._conn.commit()

    # --- Invocation querying ---

    def query_invocations(
        self,
        since: datetime | None = None,
        provider: str | None = None,
        skill: str | None = None,
    ) -> list[ToolInvocation]:
        """Query invocations with optional filters, using indexes."""
        conditions: list[str] = []
        params: list[Any] = []

        if since:
            conditions.append("timestamp >= ?")
            params.append(since.isoformat())
        if provider:
            conditions.append("provider = ?")
            params.append(provider)
        if skill:
            conditions.append("skill_context = ?")
            params.append(skill)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT conversation_id, provider, timestamp, tool_name, command, arguments, output, success, next_action, skill_context, conversation_summary FROM invocations {where} ORDER BY timestamp"

        rows = self._conn.execute(query, params).fetchall()
        return [_row_to_invocation(row) for row in rows]

    def count_invocations(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM invocations").fetchone()
        return row[0] if row else 0

    def count_conversations(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM conversations").fetchone()
        return row[0] if row else 0

    # --- Analysis result caching ---

    def save_analysis_results(self, results: list[AnalysisResult]) -> None:
        """Cache analysis results, replacing any existing for the same cluster key."""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.executemany(
            "INSERT OR REPLACE INTO analysis_results "
            "(skill, tool, failure_type, frequency, providers, root_cause, severity, "
            "skill_md_suggestion, cli_tool_suggestion, explanation, analyzed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    r.cluster.skill,
                    r.cluster.tool,
                    r.cluster.failure_type,
                    r.cluster.frequency,
                    json.dumps(sorted(r.cluster.providers)),
                    r.root_cause,
                    r.severity,
                    r.skill_md_suggestion,
                    r.cli_tool_suggestion,
                    r.explanation,
                    now,
                )
                for r in results
            ],
        )
        self._conn.commit()

    def load_analysis_results(self) -> list[AnalysisResult]:
        """Load cached analysis results."""
        rows = self._conn.execute(
            "SELECT skill, tool, failure_type, frequency, providers, root_cause, severity, "
            "skill_md_suggestion, cli_tool_suggestion, explanation FROM analysis_results "
            "ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, frequency DESC"
        ).fetchall()

        results = []
        for row in rows:
            skill, tool, failure_type, frequency, providers_json, root_cause, severity, skill_md_sug, cli_sug, explanation = row
            cluster = FailureCluster(
                skill=skill,
                tool=tool,
                failure_type=failure_type,
                frequency=frequency,
                providers=frozenset(json.loads(providers_json)),
            )
            results.append(
                AnalysisResult(
                    cluster=cluster,
                    root_cause=root_cause,
                    severity=severity,
                    skill_md_suggestion=skill_md_sug,
                    cli_tool_suggestion=cli_sug,
                    explanation=explanation,
                )
            )
        return results

    def clear_analysis_results(self) -> None:
        self._conn.execute("DELETE FROM analysis_results")
        self._conn.commit()

    # --- Analysis sessions ---

    def has_session(self, skill: str, tool: str, failure_type: str) -> bool:
        """Check if an analysis session already exists for this cluster."""
        row = self._conn.execute(
            "SELECT 1 FROM analysis_sessions WHERE skill = ? AND tool = ? AND failure_type = ?",
            (skill, tool, failure_type),
        ).fetchone()
        return row is not None

    def save_session(
        self,
        session_id: str,
        skill: str,
        tool: str,
        failure_type: str,
        frequency: int,
        providers: frozenset[str],
        analysis: str,
        first_seen: datetime | None = None,
        last_seen: datetime | None = None,
    ) -> None:
        """Store an analysis session for later resumption."""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT OR REPLACE INTO analysis_sessions "
            "(session_id, skill, tool, failure_type, frequency, providers, analysis, created_at, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, skill, tool, failure_type, frequency,
                json.dumps(sorted(providers)), analysis, now,
                first_seen.isoformat() if first_seen else None,
                last_seen.isoformat() if last_seen else None,
            ),
        )
        self._conn.commit()

    def list_sessions(self, skill: str | None = None, include_resolved: bool = False) -> list[dict[str, Any]]:
        """List stored analysis sessions."""
        conditions = []
        params: list[Any] = []
        if skill:
            conditions.append("skill = ?")
            params.append(skill)
        if not include_resolved:
            conditions.append("resolved = 0")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self._conn.execute(
            f"SELECT session_id, skill, tool, failure_type, frequency, providers, analysis, created_at, resolved, first_seen, last_seen "
            f"FROM analysis_sessions {where} ORDER BY last_seen DESC, frequency DESC",
            params,
        ).fetchall()
        return [
            {
                "session_id": r[0],
                "skill": r[1],
                "tool": r[2],
                "failure_type": r[3],
                "frequency": r[4],
                "providers": json.loads(r[5]),
                "analysis": r[6],
                "created_at": r[7],
                "resolved": bool(r[8]),
                "first_seen": r[9],
                "last_seen": r[10],
            }
            for r in rows
        ]

    def backfill_session_timespans(self) -> int:
        """Backfill first_seen/last_seen for sessions that don't have them yet."""
        sessions = self._conn.execute(
            "SELECT id, skill, tool, failure_type FROM analysis_sessions WHERE first_seen IS NULL"
        ).fetchall()
        updated = 0
        for row_id, skill, tool, failure_type in sessions:
            # Tool may be compound (e.g. "Bash:cd") — match on base tool name
            base_tool = tool.split(":")[0]
            ts_row = self._conn.execute(
                "SELECT MIN(timestamp), MAX(timestamp) FROM invocations "
                "WHERE skill_context = ? AND tool_name = ?",
                (skill, base_tool),
            ).fetchone()
            if ts_row and ts_row[0]:
                self._conn.execute(
                    "UPDATE analysis_sessions SET first_seen = ?, last_seen = ? WHERE id = ?",
                    (ts_row[0], ts_row[1], row_id),
                )
                updated += 1
        if updated:
            self._conn.commit()
        return updated

    def resolve_session(self, session_id: str, resolved: bool = True) -> None:
        """Mark a session as resolved or unresolved."""
        self._conn.execute(
            "UPDATE analysis_sessions SET resolved = ? WHERE session_id = ?",
            (int(resolved), session_id),
        )
        self._conn.commit()

    def delete_sessions(self, skill: str | None = None) -> int:
        """Delete analysis sessions. Returns count deleted."""
        if skill:
            cursor = self._conn.execute("DELETE FROM analysis_sessions WHERE skill = ?", (skill,))
        else:
            cursor = self._conn.execute("DELETE FROM analysis_sessions")
        self._conn.commit()
        return cursor.rowcount

    # --- Stats ---

    def stats(self) -> dict[str, Any]:
        """Return summary statistics about the store."""
        conv_count = self.count_conversations()
        inv_count = self.count_invocations()

        provider_counts = dict(
            self._conn.execute(
                "SELECT provider, COUNT(*) FROM invocations GROUP BY provider"
            ).fetchall()
        )
        skill_counts = dict(
            self._conn.execute(
                "SELECT skill_context, COUNT(*) FROM invocations WHERE skill_context IS NOT NULL GROUP BY skill_context ORDER BY COUNT(*) DESC LIMIT 10"
            ).fetchall()
        )
        tool_counts = dict(
            self._conn.execute(
                "SELECT tool_name, COUNT(*) FROM invocations GROUP BY tool_name ORDER BY COUNT(*) DESC LIMIT 10"
            ).fetchall()
        )
        failed_count = self._conn.execute(
            "SELECT COUNT(*) FROM invocations WHERE success = 0"
        ).fetchone()[0]

        analysis_count = self._conn.execute(
            "SELECT COUNT(*) FROM analysis_results"
        ).fetchone()[0]

        return {
            "db_path": str(self._db_path),
            "conversations": conv_count,
            "invocations": inv_count,
            "by_provider": provider_counts,
            "top_tools": tool_counts,
            "top_skills": skill_counts,
            "failed": failed_count,
            "analysis_results_cached": analysis_count,
        }


def _row_to_invocation(row: tuple) -> ToolInvocation:
    (conversation_id, provider, timestamp_str, tool_name, command, arguments_json, output, success, next_action, skill_context, conversation_summary) = row
    return ToolInvocation(
        conversation_id=conversation_id,
        provider=provider,
        timestamp=datetime.fromisoformat(timestamp_str),
        tool_name=tool_name,
        command=command,
        arguments=json.loads(arguments_json),
        output=output,
        success=bool(success),
        next_action=next_action,
        skill_context=skill_context,
        conversation_summary=conversation_summary,
    )
