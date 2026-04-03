"""Tests for Claude Code provider JSONL parsing."""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path


from refainery.models import ConversationRef
from refainery.providers.claude import ClaudeProvider


def _user_msg(text: str, cwd: str | None = None, ts: str = "2024-01-01T10:00:00Z") -> str:
    msg: dict = {"type": "user", "timestamp": ts, "message": {"role": "user", "content": text}}
    if cwd:
        msg["cwd"] = cwd
    return json.dumps(msg)


def _user_msg_with_tool_result(
    tool_use_id: str, content: str, ts: str = "2024-01-01T10:01:00Z"
) -> str:
    return json.dumps(
        {
            "type": "user",
            "timestamp": ts,
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": content}],
            },
        }
    )


def _assistant_msg_with_tool_use(
    tool_id: str,
    tool_name: str,
    tool_input: dict,
    ts: str = "2024-01-01T10:00:30Z",
    text: str | None = None,
    msg_id: str | None = None,
) -> str:
    content = [{"type": "tool_use", "id": tool_id, "name": tool_name, "input": tool_input}]
    if text:
        content.insert(0, {"type": "text", "text": text})
    msg: dict = {
        "type": "assistant",
        "timestamp": ts,
        "message": {"role": "assistant", "content": content},
    }
    if msg_id:
        msg["message"]["id"] = msg_id
    return json.dumps(msg)


def _assistant_text(text: str, ts: str = "2024-01-01T10:02:00Z") -> str:
    return json.dumps(
        {
            "type": "assistant",
            "timestamp": ts,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
        }
    )


def _summary(text: str) -> str:
    return json.dumps({"type": "summary", "summary": text})


def _make_provider_and_conv(lines: list[str]) -> tuple[ClaudeProvider, ConversationRef]:
    """Write JSONL lines to a temp file and return a provider + conversation ref."""
    tmpdir = tempfile.mkdtemp()
    project_dir = Path(tmpdir) / "test-project"
    project_dir.mkdir()
    jsonl_file = project_dir / "test-conv.jsonl"
    jsonl_file.write_text("\n".join(lines) + "\n")

    provider = ClaudeProvider(projects_dir=Path(tmpdir))
    conv = ConversationRef(
        conversation_id="test-conv",
        provider="claude",
        path=str(jsonl_file),
        timestamp=datetime.now(timezone.utc),
        project_path=str(project_dir),
    )
    return provider, conv


class TestBasicExtraction:
    def test_extracts_bash_tool_invocation(self):
        lines = [
            _user_msg("run git status"),
            _assistant_msg_with_tool_use("tu1", "Bash", {"command": "git status"}),
            _user_msg_with_tool_result("tu1", "On branch main\nnothing to commit"),
            _assistant_text("Everything looks clean."),
        ]
        provider, conv = _make_provider_and_conv(lines)
        invocations = provider.extract_invocations(conv)

        assert len(invocations) == 1
        inv = invocations[0]
        assert inv.tool_name == "Bash"
        assert inv.command == "git status"
        assert "nothing to commit" in inv.output
        assert inv.success is True
        assert inv.next_action == "continue"

    def test_extracts_read_tool(self):
        lines = [
            _user_msg("read the file"),
            _assistant_msg_with_tool_use("tu1", "Read", {"file_path": "/src/main.rs"}),
            _user_msg_with_tool_result("tu1", "fn main() {}"),
        ]
        provider, conv = _make_provider_and_conv(lines)
        invocations = provider.extract_invocations(conv)

        assert len(invocations) == 1
        assert invocations[0].tool_name == "Read"
        assert invocations[0].command is None
        assert invocations[0].arguments["file_path"] == "/src/main.rs"

    def test_detects_error_output(self):
        lines = [
            _user_msg("find the file"),
            _assistant_msg_with_tool_use("tu1", "Bash", {"command": "cat /nonexistent"}),
            _user_msg_with_tool_result("tu1", "cat: /nonexistent: No such file or directory\nExit code 1"),
        ]
        provider, conv = _make_provider_and_conv(lines)
        invocations = provider.extract_invocations(conv)

        assert len(invocations) == 1
        assert invocations[0].success is False


class TestSkillContext:
    def test_tracks_skill_context(self):
        lines = [
            _user_msg("check jira"),
            _assistant_msg_with_tool_use("tu1", "Skill", {"skill": "jira"}),
            _user_msg_with_tool_result("tu1", "Skill loaded."),
            _assistant_msg_with_tool_use("tu2", "Bash", {"command": "jira issue list"}, ts="2024-01-01T10:01:00Z"),
            _user_msg_with_tool_result("tu2", "PROJ-123 Fix bug", ts="2024-01-01T10:01:30Z"),
        ]
        provider, conv = _make_provider_and_conv(lines)
        invocations = provider.extract_invocations(conv)

        # The Skill call itself is extracted
        skill_inv = next(i for i in invocations if i.tool_name == "Skill")
        assert skill_inv.skill_context == "jira"

        # The subsequent Bash call inherits skill context
        bash_inv = next(i for i in invocations if i.tool_name == "Bash")
        assert bash_inv.skill_context == "jira"


class TestNextAction:
    def test_next_action_tool(self):
        lines = [
            _user_msg("do stuff"),
            _assistant_msg_with_tool_use("tu1", "Read", {"file_path": "/a.txt"}, ts="2024-01-01T10:00:00Z"),
            _user_msg_with_tool_result("tu1", "contents", ts="2024-01-01T10:00:30Z"),
            _assistant_msg_with_tool_use("tu2", "Edit", {"file_path": "/a.txt"}, ts="2024-01-01T10:01:00Z"),
            _user_msg_with_tool_result("tu2", "done", ts="2024-01-01T10:01:30Z"),
        ]
        provider, conv = _make_provider_and_conv(lines)
        invocations = provider.extract_invocations(conv)

        assert invocations[0].next_action == "tool:Edit"

    def test_next_action_struggle(self):
        lines = [
            _user_msg("fix the bug"),
            _assistant_msg_with_tool_use("tu1", "Bash", {"command": "make build"}, ts="2024-01-01T10:00:00Z"),
            _user_msg_with_tool_result("tu1", "error: compilation failed", ts="2024-01-01T10:00:30Z"),
            _assistant_text("I apologize, that didn't work. Let me try a different approach.", ts="2024-01-01T10:01:00Z"),
        ]
        provider, conv = _make_provider_and_conv(lines)
        invocations = provider.extract_invocations(conv)

        assert invocations[0].next_action == "struggle"


class TestConversationSummary:
    def test_captures_summary(self):
        lines = [
            _summary("Debugging authentication issue"),
            _user_msg("check the auth code"),
            _assistant_msg_with_tool_use("tu1", "Bash", {"command": "grep -r 'auth' ."}),
            _user_msg_with_tool_result("tu1", "src/auth.py:def authenticate()"),
        ]
        provider, conv = _make_provider_and_conv(lines)
        invocations = provider.extract_invocations(conv)

        assert invocations[0].conversation_summary == "Debugging authentication issue"


class TestDiscovery:
    def test_discovers_conversations(self):
        tmpdir = tempfile.mkdtemp()
        project_dir = Path(tmpdir) / "test-project"
        project_dir.mkdir()
        (project_dir / "conv1.jsonl").write_text(_user_msg("hello") + "\n")
        (project_dir / "conv2.jsonl").write_text(_user_msg("world") + "\n")
        # agent files should be skipped
        (project_dir / "agent-sub.jsonl").write_text(_user_msg("sub") + "\n")

        provider = ClaudeProvider(projects_dir=Path(tmpdir))
        convs = provider.discover_conversations()

        assert len(convs) == 2
        ids = {c.conversation_id for c in convs}
        assert ids == {"conv1", "conv2"}

    def test_filters_by_since(self):
        tmpdir = tempfile.mkdtemp()
        project_dir = Path(tmpdir) / "test-project"
        project_dir.mkdir()
        (project_dir / "old.jsonl").write_text(_user_msg("old") + "\n")

        provider = ClaudeProvider(projects_dir=Path(tmpdir))
        # Use a future timestamp as cutoff — should filter everything
        future = datetime(2030, 1, 1, tzinfo=timezone.utc)
        convs = provider.discover_conversations(since=future)
        assert len(convs) == 0
