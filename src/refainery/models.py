from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ToolInvocation:
    """A single tool call extracted from a conversation, normalized across providers."""

    conversation_id: str
    provider: str
    timestamp: datetime
    tool_name: str
    command: str | None
    arguments: dict[str, Any]
    output: str
    success: bool
    next_action: str | None = None
    skill_context: str | None = None
    conversation_summary: str | None = None


@dataclass
class ConversationRef:
    """Lightweight reference to a conversation for discovery before full extraction."""

    conversation_id: str
    provider: str
    path: str
    timestamp: datetime
    project_path: str | None = None
    content_hash: str | None = None  # Stable change indicator (file mtime string or bubble count)


@dataclass
class FailureCluster:
    """A group of related failures, ready for LLM analysis."""

    skill: str
    tool: str
    failure_type: str
    occurrences: list[ToolInvocation] = field(default_factory=list)
    providers: frozenset[str] = field(default_factory=frozenset)
    frequency: int = 0

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.skill, self.tool, self.failure_type)

    @property
    def first_seen(self) -> datetime | None:
        if not self.occurrences:
            return None
        return min(inv.timestamp for inv in self.occurrences)

    @property
    def last_seen(self) -> datetime | None:
        if not self.occurrences:
            return None
        return max(inv.timestamp for inv in self.occurrences)

    @property
    def timespan(self) -> str:
        first, last = self.first_seen, self.last_seen
        if not first or not last:
            return ""
        f, l = first.strftime("%Y-%m-%d"), last.strftime("%Y-%m-%d")
        return f if f == l else f"{f} → {l}"


@dataclass
class AnalysisResult:
    """Output from Claude analysis of a failure cluster."""

    cluster: FailureCluster
    root_cause: str
    severity: str
    skill_md_suggestion: str | None = None
    cli_tool_suggestion: str | None = None
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.cluster.skill,
            "tool": self.cluster.tool,
            "failure_type": self.cluster.failure_type,
            "frequency": self.cluster.frequency,
            "providers": sorted(self.cluster.providers),
            "root_cause": self.root_cause,
            "severity": self.severity,
            "skill_md_suggestion": self.skill_md_suggestion,
            "cli_tool_suggestion": self.cli_tool_suggestion,
            "explanation": self.explanation,
        }
