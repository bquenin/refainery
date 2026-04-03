"""Cursor conversation provider.

Extracts tool invocations from Cursor's SQLite databases.
Global DB at ~/Library/Application Support/Cursor/User/globalStorage/state.vscdb
Workspace DBs at ~/Library/Application Support/Cursor/User/workspaceStorage/*/state.vscdb

Reference: mnemonai src/providers/cursor.rs
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from refainery.models import ConversationRef, ToolInvocation
from refainery.providers.tool_map import normalize_tool_name

# Bubble type constants (from cursor.rs)
BUBBLE_TYPE_USER = 1
BUBBLE_TYPE_ASSISTANT = 2


def _cursor_user_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "Cursor" / "User"


def _open_readonly(db_path: Path) -> sqlite3.Connection | None:
    """Open a SQLite database in read-only mode, or None if unavailable."""
    if not db_path.exists():
        return None
    try:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None


def _parse_bubble(json_str: str) -> dict[str, Any] | None:
    """Parse a bubble JSON string into a dict with normalized fields.

    Reference: cursor.rs parse_bubble() lines 1020-1127
    """
    try:
        v = json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return None

    bubble_type = v.get("type")
    if not isinstance(bubble_type, int):
        return None

    text = v.get("text", "") or ""

    # richText fallback for user messages
    rich_text = v.get("richText")
    if rich_text and not text:
        if isinstance(rich_text, str):
            text = _extract_text_from_richtext(rich_text) or ""
        elif isinstance(rich_text, dict):
            text = _extract_text_from_richtext(json.dumps(rich_text)) or ""

    created_at = v.get("createdAt")

    # Tool data
    tool_former = v.get("toolFormerData")
    tool_name = None
    tool_args: dict[str, Any] = {}
    tool_result = ""
    tool_status = None

    if tool_former and isinstance(tool_former, dict):
        tool_name = tool_former.get("name")

        # Parse args: try rawArgs first, then params (cursor.rs lines 1073-1095)
        raw_args = tool_former.get("rawArgs") or tool_former.get("params")
        if isinstance(raw_args, str) and raw_args:
            try:
                tool_args = json.loads(raw_args)
                if not isinstance(tool_args, dict):
                    tool_args = {"raw": raw_args}
            except json.JSONDecodeError:
                tool_args = {"raw": raw_args}
        elif isinstance(raw_args, dict):
            tool_args = raw_args
        elif isinstance(raw_args, list):
            tool_args = {"items": raw_args}

        tool_result = tool_former.get("result") or ""
        if not isinstance(tool_result, str):
            tool_result = json.dumps(tool_result) if tool_result else ""

        # Status: check additionalData.status first, then status
        additional = tool_former.get("additionalData")
        if isinstance(additional, dict):
            tool_status = additional.get("status")
        if tool_status is None:
            tool_status = tool_former.get("status")

    return {
        "bubble_type": bubble_type,
        "text": text,
        "created_at": created_at,
        "tool_name": tool_name,
        "tool_args": tool_args,
        "tool_result": tool_result,
        "tool_status": tool_status,
    }


def _extract_text_from_richtext(rich_text_str: str) -> str | None:
    """Extract plain text from Cursor's Lexical richText JSON.

    Reference: cursor.rs extract_text_from_richtext() lines 1131-1170
    """
    try:
        v = json.loads(rich_text_str)
    except (json.JSONDecodeError, TypeError):
        return None

    parts: list[str] = []
    _collect_text_nodes(v, parts)
    return "".join(parts) if parts else None


def _collect_text_nodes(node: Any, parts: list[str]) -> None:
    if not isinstance(node, dict):
        return

    node_type = node.get("type")
    if node_type == "text":
        text = node.get("text", "")
        if text:
            parts.append(text)
        return
    if node_type == "linebreak":
        parts.append("\n")
        return

    children = node.get("children")
    if isinstance(children, list):
        for i, child in enumerate(children):
            _collect_text_nodes(child, parts)
            if (
                i < len(children) - 1
                and isinstance(child, dict)
                and child.get("type") == "paragraph"
            ):
                parts.append("\n")

    root = node.get("root")
    if isinstance(root, dict):
        _collect_text_nodes(root, parts)


def _parse_cursor_timestamp(ts: Any) -> datetime:
    """Parse a Cursor timestamp (ISO string or millis int)."""
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            pass
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
    return datetime.now(timezone.utc)


def _check_success(output: str) -> bool:
    if not output:
        return True
    lower = output.lower()
    return not any(
        kw in lower
        for kw in ["error", "not found", "no such", "failed", "invalid", "permission denied"]
    )


class CursorProvider:
    """Extracts tool invocations from Cursor's SQLite databases."""

    provider_name = "cursor"

    def __init__(self, user_dir: Path | None = None) -> None:
        self._user_dir = user_dir or _cursor_user_dir()
        self._global_db_path = self._user_dir / "globalStorage" / "state.vscdb"
        self._workspace_storage = self._user_dir / "workspaceStorage"

    def detect(self) -> bool:
        return self._global_db_path.exists()

    def discover_conversations(self, since: datetime | None = None) -> list[ConversationRef]:
        conversations: list[ConversationRef] = []

        conn = _open_readonly(self._global_db_path)
        if conn is None:
            return conversations

        try:
            # Fast index scan: enumerate conversations by GROUP BY on bubbleId: prefix
            # Reference: cursor.rs query_conv_infos() lines 218-243
            cursor = conn.execute(
                "SELECT SUBSTR(key, 10, INSTR(SUBSTR(key, 10), ':') - 1) as conv_id, "
                "COUNT(*) as cnt "
                "FROM cursorDiskKV "
                "WHERE key >= 'bubbleId:' AND key < 'bubbleId;' "
                "GROUP BY conv_id"
            )

            # Build workspace map for project path resolution
            workspace_map = self._build_workspace_map()

            for row in cursor.fetchall():
                conv_id, count = row[0], row[1]
                if count == 0:
                    continue

                # Get timestamp from workspace map or use epoch
                ws_info = workspace_map.get(conv_id)
                if ws_info:
                    ts = _parse_cursor_timestamp(ws_info.get("timestamp"))
                    project_path = ws_info.get("path")
                else:
                    ts = datetime.now(timezone.utc)
                    project_path = None

                if since and ts < since:
                    continue

                # Use bubble count as stable content hash (timestamps drift)
                content_hash = str(count)

                conversations.append(
                    ConversationRef(
                        conversation_id=conv_id,
                        provider="cursor",
                        path=str(self._global_db_path),
                        timestamp=ts,
                        project_path=project_path,
                        content_hash=content_hash,
                    )
                )
        except sqlite3.Error:
            pass
        finally:
            conn.close()

        return conversations

    def extract_invocations(self, conversation: ConversationRef) -> list[ToolInvocation]:
        """Load all bubbles for a conversation and extract tool invocations."""
        conn = _open_readonly(self._global_db_path)
        if conn is None:
            return []

        invocations: list[ToolInvocation] = []

        try:
            # Fetch all bubbles ordered by ROWID (insertion order)
            # Reference: cursor.rs load_bubbles() lines 190-213
            prefix = f"bubbleId:{conversation.conversation_id}:"
            prefix_end = f"bubbleId:{conversation.conversation_id};"

            cursor = conn.execute(
                "SELECT CAST(value AS TEXT) FROM cursorDiskKV "
                "WHERE key >= ? AND key < ? ORDER BY ROWID",
                (prefix, prefix_end),
            )

            bubbles = []
            for (json_str,) in cursor.fetchall():
                bubble = _parse_bubble(json_str)
                if bubble:
                    bubbles.append(bubble)

            # Process bubbles into invocations
            for i, bubble in enumerate(bubbles):
                if bubble["tool_name"] is None:
                    continue

                normalized_name = normalize_tool_name("cursor", bubble["tool_name"])
                tool_args = bubble["tool_args"]
                command = tool_args.get("command") if normalized_name == "Bash" else None

                output = bubble["tool_result"]

                # Determine next_action from subsequent bubbles
                next_action = None
                for j in range(i + 1, min(i + 3, len(bubbles))):
                    next_bubble = bubbles[j]
                    if next_bubble["bubble_type"] == BUBBLE_TYPE_ASSISTANT:
                        if next_bubble["tool_name"]:
                            next_action = f"tool:{normalize_tool_name('cursor', next_bubble['tool_name'])}"
                        elif next_bubble["text"]:
                            from refainery.providers.claude import _has_struggle_signals

                            next_action = "struggle" if _has_struggle_signals(next_bubble["text"]) else "continue"
                        break

                inv = ToolInvocation(
                    conversation_id=conversation.conversation_id,
                    provider="cursor",
                    timestamp=_parse_cursor_timestamp(bubble["created_at"]),
                    tool_name=normalized_name,
                    command=command,
                    arguments=tool_args,
                    output=output,
                    success=_check_success(output),
                    next_action=next_action,
                    skill_context=None,  # Cursor doesn't have the Skill tool concept
                    conversation_summary=None,
                )
                invocations.append(inv)

        except sqlite3.Error:
            pass
        finally:
            conn.close()

        return invocations

    def _build_workspace_map(self) -> dict[str, dict[str, Any]]:
        """Build a map from conversation ID -> workspace info.

        Reference: cursor.rs build_workspace_map() lines 103-176
        """
        workspace_map: dict[str, dict[str, Any]] = {}

        if not self._workspace_storage.is_dir():
            return workspace_map

        for ws_dir in self._workspace_storage.iterdir():
            if not ws_dir.is_dir():
                continue

            db_path = ws_dir / "state.vscdb"
            conn = _open_readonly(db_path)
            if conn is None:
                continue

            try:
                # Get workspace path
                ws_json_path = ws_dir / "workspace.json"
                ws_path = None
                if ws_json_path.exists():
                    try:
                        ws_data = json.loads(ws_json_path.read_text())
                        uri = ws_data.get("folder") or ws_data.get("workspace")
                        if uri and isinstance(uri, str) and uri.startswith("file://"):
                            ws_path = uri[len("file://"):]
                    except (json.JSONDecodeError, OSError):
                        pass

                # Read composer.composerData for conversation IDs
                try:
                    row = conn.execute(
                        "SELECT value FROM ItemTable WHERE key = 'composer.composerData'"
                    ).fetchone()
                except sqlite3.Error:
                    continue

                if row is None:
                    continue

                try:
                    parsed = json.loads(row[0])
                    composers = parsed.get("allComposers", [])
                except (json.JSONDecodeError, TypeError):
                    continue

                for composer in composers:
                    if not isinstance(composer, dict):
                        continue
                    comp_id = composer.get("composerId")
                    if not comp_id:
                        continue

                    timestamp = composer.get("lastUpdatedAt") or composer.get("createdAt")
                    title = composer.get("name") or None

                    workspace_map[comp_id] = {
                        "path": ws_path,
                        "title": title,
                        "timestamp": timestamp,
                    }
            except sqlite3.Error:
                pass
            finally:
                conn.close()

        return workspace_map
