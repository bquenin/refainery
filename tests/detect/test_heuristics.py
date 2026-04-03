"""Tests for failure detection heuristics."""

from datetime import datetime, timezone

from refainery.detect.heuristics import (
    detect_abandoned_tools,
    detect_command_mutations,
    detect_error_outputs,
    detect_retry_chains,
    detect_struggle_signals,
)
from refainery.models import ToolInvocation


def _inv(
    tool: str = "Bash",
    command: str | None = "echo hello",
    success: bool = True,
    next_action: str | None = None,
    skill: str | None = None,
    provider: str = "claude",
    ts_minute: int = 0,
) -> ToolInvocation:
    return ToolInvocation(
        conversation_id="conv1",
        provider=provider,
        timestamp=datetime(2024, 1, 1, 10, ts_minute, tzinfo=timezone.utc),
        tool_name=tool,
        command=command,
        arguments={"command": command} if command else {},
        output="some output",
        success=success,
        next_action=next_action,
        skill_context=skill,
    )


class TestRetryChains:
    def test_detects_retry_chain(self):
        invocations = [
            _inv(command="git status", ts_minute=0),
            _inv(command="git status --short", ts_minute=1),
            _inv(command="git status -s", ts_minute=2),
        ]
        clusters = detect_retry_chains(invocations)
        assert len(clusters) == 1
        assert clusters[0].failure_type == "retry_chain"
        assert clusters[0].frequency == 3

    def test_no_chain_for_different_tools(self):
        invocations = [
            _inv(tool="Bash", command="ls", ts_minute=0),
            _inv(tool="Read", command=None, ts_minute=1),
            _inv(tool="Bash", command="ls -la", ts_minute=2),
        ]
        clusters = detect_retry_chains(invocations)
        assert len(clusters) == 0

    def test_single_invocation_no_chain(self):
        clusters = detect_retry_chains([_inv()])
        assert len(clusters) == 0


class TestErrorOutputs:
    def test_groups_failures_by_skill_and_tool(self):
        invocations = [
            _inv(tool="Bash", success=False, skill="jira", ts_minute=0),
            _inv(tool="Bash", success=False, skill="jira", ts_minute=1),
            _inv(tool="Read", success=False, skill="jira", ts_minute=2),
            _inv(tool="Bash", success=True, skill="jira", ts_minute=3),
        ]
        clusters = detect_error_outputs(invocations)
        assert len(clusters) == 2

        bash_cluster = next(c for c in clusters if c.tool == "Bash")
        assert bash_cluster.frequency == 2
        assert bash_cluster.skill == "jira"

    def test_no_failures(self):
        invocations = [_inv(success=True), _inv(success=True)]
        clusters = detect_error_outputs(invocations)
        assert len(clusters) == 0


class TestStruggleSignals:
    def test_detects_struggle(self):
        invocations = [
            _inv(next_action="struggle", ts_minute=0),
            _inv(next_action="struggle", ts_minute=1),
            _inv(next_action="continue", ts_minute=2),
        ]
        clusters = detect_struggle_signals(invocations)
        assert len(clusters) == 1
        assert clusters[0].frequency == 2

    def test_no_struggles(self):
        invocations = [_inv(next_action="continue")]
        clusters = detect_struggle_signals(invocations)
        assert len(clusters) == 0


class TestCommandMutations:
    def test_detects_mutations(self):
        invocations = [
            _inv(command="curl http://api.example.com/v1/users", ts_minute=0),
            _inv(command="curl -H 'Auth: token' http://api.example.com/v1/users", ts_minute=1),
            _inv(command="curl -H 'Auth: token' -X POST http://api.example.com/v1/users", ts_minute=2),
        ]
        clusters = detect_command_mutations(invocations)
        assert len(clusters) == 1
        assert clusters[0].failure_type == "command_mutation"

    def test_no_mutations_for_identical_commands(self):
        invocations = [
            _inv(command="ls -la", ts_minute=0),
            _inv(command="ls -la", ts_minute=1),
            _inv(command="ls -la", ts_minute=2),
        ]
        clusters = detect_command_mutations(invocations)
        assert len(clusters) == 0


class TestAbandonedTools:
    def test_detects_abandoned_tool(self):
        invocations = [
            _inv(tool="Grep", success=False, ts_minute=0),
            _inv(tool="Bash", command="find . -name '*.py'", success=True, ts_minute=1),
        ]
        clusters = detect_abandoned_tools(invocations)
        assert len(clusters) == 1
        assert clusters[0].failure_type == "abandoned_tool"
        assert clusters[0].tool == "Grep"

    def test_no_abandon_if_tool_reused(self):
        invocations = [
            _inv(tool="Grep", success=False, ts_minute=0),
            _inv(tool="Bash", success=True, ts_minute=1),
            _inv(tool="Grep", success=True, ts_minute=2),
        ]
        clusters = detect_abandoned_tools(invocations)
        assert len(clusters) == 0
