"""Tests for the SQLite store."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from refainery.models import AnalysisResult, ConversationRef, FailureCluster, ToolInvocation
from refainery.store import Store


def _make_store() -> Store:
    tmpdir = tempfile.mkdtemp()
    return Store(db_path=Path(tmpdir) / "test.db")


def _inv(
    conv_id: str = "conv1",
    provider: str = "claude",
    tool: str = "Bash",
    command: str | None = "echo hello",
    success: bool = True,
    skill: str | None = None,
    ts: str = "2024-06-15T10:00:00+00:00",
) -> ToolInvocation:
    return ToolInvocation(
        conversation_id=conv_id,
        provider=provider,
        timestamp=datetime.fromisoformat(ts),
        tool_name=tool,
        command=command,
        arguments={"command": command} if command else {},
        output="some output",
        success=success,
        skill_context=skill,
    )


def _conv(
    conv_id: str = "conv1",
    provider: str = "claude",
    ts: str = "2024-06-15T10:00:00+00:00",
    content_hash: str = "12345.0:1024",
) -> ConversationRef:
    return ConversationRef(
        conversation_id=conv_id,
        provider=provider,
        path="/fake/path.jsonl",
        timestamp=datetime.fromisoformat(ts),
        project_path="/fake/project",
        content_hash=content_hash,
    )


class TestWatermark:
    def test_needs_reindex_when_not_indexed(self):
        store = _make_store()
        assert store.needs_reindex(_conv()) is True
        store.close()

    def test_no_reindex_when_up_to_date(self):
        store = _make_store()
        conv = _conv()
        store.mark_indexed(conv)
        store.commit()
        assert store.needs_reindex(conv) is False
        store.close()

    def test_needs_reindex_when_content_hash_changed(self):
        store = _make_store()
        conv = _conv(content_hash="12345.0:1024")
        store.mark_indexed(conv)
        store.commit()

        changed = _conv(content_hash="12346.0:2048")
        assert store.needs_reindex(changed) is True
        store.close()

    def test_no_reindex_when_only_timestamp_changed(self):
        store = _make_store()
        conv = _conv(ts="2024-06-15T10:00:00+00:00", content_hash="same")
        store.mark_indexed(conv)
        store.commit()

        # Timestamp changed but content_hash is the same — should NOT reindex
        same_content = _conv(ts="2024-06-16T10:00:00+00:00", content_hash="same")
        assert store.needs_reindex(same_content) is False
        store.close()


class TestInvocationStorage:
    def test_insert_and_query(self):
        store = _make_store()
        invocations = [_inv(), _inv(tool="Read", command=None)]
        store.insert_invocations(invocations)
        store.commit()

        result = store.query_invocations()
        assert len(result) == 2
        assert result[0].tool_name == "Bash"
        assert result[0].command == "echo hello"
        assert result[1].tool_name == "Read"
        store.close()

    def test_query_with_provider_filter(self):
        store = _make_store()
        store.insert_invocations([
            _inv(provider="claude"),
            _inv(provider="cursor"),
        ])
        store.commit()

        result = store.query_invocations(provider="claude")
        assert len(result) == 1
        assert result[0].provider == "claude"
        store.close()

    def test_query_with_skill_filter(self):
        store = _make_store()
        store.insert_invocations([
            _inv(skill="jira"),
            _inv(skill=None),
        ])
        store.commit()

        result = store.query_invocations(skill="jira")
        assert len(result) == 1
        assert result[0].skill_context == "jira"
        store.close()

    def test_query_with_since_filter(self):
        store = _make_store()
        store.insert_invocations([
            _inv(ts="2024-06-10T10:00:00+00:00"),
            _inv(ts="2024-06-20T10:00:00+00:00"),
        ])
        store.commit()

        cutoff = datetime(2024, 6, 15, tzinfo=timezone.utc)
        result = store.query_invocations(since=cutoff)
        assert len(result) == 1
        store.close()

    def test_delete_and_reindex(self):
        store = _make_store()
        store.insert_invocations([_inv(), _inv()])
        store.commit()
        assert store.count_invocations() == 2

        store.delete_invocations("conv1", "claude")
        store.insert_invocations([_inv()])
        store.commit()
        assert store.count_invocations() == 1
        store.close()


class TestAnalysisResults:
    def test_save_and_load(self):
        store = _make_store()
        cluster = FailureCluster(
            skill="jira", tool="Bash", failure_type="retry_chain",
            frequency=5, providers=frozenset(["claude"]),
        )
        result = AnalysisResult(
            cluster=cluster,
            root_cause="missing_instructions",
            severity="high",
            skill_md_suggestion="Add flag docs",
            explanation="Agent doesn't know about --json flag.",
        )
        store.save_analysis_results([result])

        loaded = store.load_analysis_results()
        assert len(loaded) == 1
        assert loaded[0].root_cause == "missing_instructions"
        assert loaded[0].severity == "high"
        assert loaded[0].cluster.skill == "jira"
        assert loaded[0].skill_md_suggestion == "Add flag docs"
        store.close()

    def test_upsert_replaces(self):
        store = _make_store()
        cluster = FailureCluster(
            skill="jira", tool="Bash", failure_type="retry_chain",
            frequency=5, providers=frozenset(["claude"]),
        )
        store.save_analysis_results([AnalysisResult(
            cluster=cluster, root_cause="old", severity="low", explanation="old",
        )])
        store.save_analysis_results([AnalysisResult(
            cluster=cluster, root_cause="new", severity="high", explanation="new",
        )])

        loaded = store.load_analysis_results()
        assert len(loaded) == 1
        assert loaded[0].root_cause == "new"
        store.close()


class TestStats:
    def test_stats_on_empty_db(self):
        store = _make_store()
        stats = store.stats()
        assert stats["conversations"] == 0
        assert stats["invocations"] == 0
        store.close()

    def test_stats_with_data(self):
        store = _make_store()
        store.insert_invocations([
            _inv(provider="claude", skill="jira"),
            _inv(provider="cursor", tool="Read"),
        ])
        store.mark_indexed(_conv())
        store.commit()

        stats = store.stats()
        assert stats["conversations"] == 1
        assert stats["invocations"] == 2
        assert stats["by_provider"]["claude"] == 1
        assert stats["by_provider"]["cursor"] == 1
        store.close()
