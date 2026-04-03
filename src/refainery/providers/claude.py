"""Claude Code conversation provider.

Parses JSONL conversation files from ~/.claude/projects/ and extracts
normalized ToolInvocation objects with skill context and next-action tracking.

Reference: mnemonai src/claude.rs, src/history/parser.rs, src/history/path.rs
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from refainery.models import ConversationRef, ToolInvocation

# Phrases indicating the agent is struggling after a tool result
STRUGGLE_PHRASES = [
    "let me try",
    "that didn't work",
    "that didn't seem to",
    "I apologize",
    "seems like",
    "try a different approach",
    "try another",
    "unfortunately",
    "doesn't seem to",
    "let me attempt",
    "not working",
    "didn't produce",
]

# Error indicators in tool output
ERROR_PATTERNS = re.compile(
    r"(?i)\b(?:error|not found|no such file|no such directory|usage:|invalid|"
    r"failed|permission denied|command not found|connection refused|timeout)\b"
)
EXIT_CODE_PATTERN = re.compile(r"(?:Exit code|exit code|exit status)\s+([1-9]\d*)")


def _projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def _parse_timestamp(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp, falling back to now on failure."""
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def _extract_tool_result_text(content: Any) -> str:
    """Extract text from a tool_result content field.

    Content can be:
    - None
    - A string
    - A list of content blocks (each may have a "text" field)
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text", "")
                if text:
                    parts.append(text)
        return "\n".join(parts)
    return str(content)


def _check_success(output: str) -> bool:
    """Heuristic: does the tool output look like an error?"""
    if not output:
        return True
    if EXIT_CODE_PATTERN.search(output):
        return False
    if ERROR_PATTERNS.search(output):
        return False
    return True


def _has_struggle_signals(text: str) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in STRUGGLE_PHRASES)


def _extract_text_from_blocks(blocks: list[dict]) -> str:
    return " ".join(b.get("text", "") for b in blocks if b.get("type") == "text")


class ClaudeProvider:
    """Extracts tool invocations from Claude Code JSONL conversation files."""

    provider_name = "claude"

    def __init__(self, projects_dir: Path | None = None) -> None:
        self._projects_dir = projects_dir or _projects_dir()

    def detect(self) -> bool:
        return self._projects_dir.is_dir()

    def discover_conversations(self, since: datetime | None = None) -> list[ConversationRef]:
        conversations: list[ConversationRef] = []

        if not self._projects_dir.is_dir():
            return conversations

        for project_dir in self._projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            for jsonl_file in project_dir.glob("*.jsonl"):
                # Skip subagent files (mnemonai: loader.rs line 240-247)
                if jsonl_file.name.startswith("agent-"):
                    continue

                stat = jsonl_file.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                if since and mtime < since:
                    continue

                # Use file size + mtime as a stable content hash
                content_hash = f"{stat.st_mtime}:{stat.st_size}"

                conversations.append(
                    ConversationRef(
                        conversation_id=jsonl_file.stem,
                        provider="claude",
                        path=str(jsonl_file),
                        timestamp=mtime,
                        project_path=str(project_dir),
                        content_hash=content_hash,
                    )
                )

        return conversations

    def extract_invocations(self, conversation: ConversationRef) -> list[ToolInvocation]:
        """Parse a JSONL file and extract all tool invocations with context."""
        path = Path(conversation.path)
        if not path.exists():
            return []

        # State machine
        pending_tool_uses: dict[str, dict] = {}  # tool_use_id -> {name, input, timestamp}
        current_skill: str | None = None
        conversation_summary: str | None = None
        invocations: list[ToolInvocation] = []

        # For deduplication of streaming entries: track last seen assistant message ID
        seen_message_ids: set[str] = set()
        # Buffer: tool uses from the current assistant message (may be overwritten by streaming)
        current_assistant_tool_uses: list[dict] = []
        current_assistant_msg_id: str | None = None

        # For next_action tracking: invocations created since the last assistant text
        pending_next_action: list[ToolInvocation] = []

        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type")

                if entry_type == "summary":
                    if conversation_summary is None:
                        conversation_summary = entry.get("summary")

                elif entry_type == "assistant":
                    message = entry.get("message", {})
                    timestamp = entry.get("timestamp", "")
                    msg_id = message.get("id")

                    # Handle streaming deduplication: if same message ID, replace pending tool_uses
                    if msg_id and msg_id == current_assistant_msg_id:
                        # Same streaming message — update tool_uses from latest version
                        for tu in current_assistant_tool_uses:
                            pending_tool_uses.pop(tu["id"], None)
                        current_assistant_tool_uses.clear()
                    elif msg_id and msg_id in seen_message_ids:
                        # Already processed this message ID fully, skip
                        continue

                    current_assistant_msg_id = msg_id
                    current_assistant_tool_uses.clear()

                    content = message.get("content", [])
                    if not isinstance(content, list):
                        continue

                    # Check for text blocks that update next_action on pending invocations
                    for block in content:
                        block_type = block.get("type")

                        if block_type == "text":
                            text = block.get("text", "")
                            if text and pending_next_action:
                                if _has_struggle_signals(text):
                                    action = "struggle"
                                else:
                                    action = "continue"
                                for inv in pending_next_action:
                                    if inv.next_action is None:
                                        inv.next_action = action
                                pending_next_action.clear()

                        elif block_type == "tool_use":
                            tool_id = block.get("id", "")
                            tool_name = block.get("name", "")
                            tool_input = block.get("input", {})

                            # Track skill context
                            if tool_name == "Skill":
                                skill_name = tool_input.get("skill")
                                if skill_name:
                                    current_skill = skill_name

                            pending_tool_uses[tool_id] = {
                                "name": tool_name,
                                "input": tool_input,
                                "timestamp": timestamp,
                            }
                            current_assistant_tool_uses.append({"id": tool_id})

                            # Update next_action on previous invocations
                            if pending_next_action:
                                for inv in pending_next_action:
                                    if inv.next_action is None:
                                        inv.next_action = f"tool:{tool_name}"
                                pending_next_action.clear()

                    if msg_id:
                        seen_message_ids.add(msg_id)

                elif entry_type == "user":
                    message = entry.get("message", {})
                    user_content = message.get("content", "")

                    # Process tool results
                    if isinstance(user_content, list):
                        for block in user_content:
                            if block.get("type") == "tool_result":
                                tool_use_id = block.get("tool_use_id", "")
                                tool_info = pending_tool_uses.pop(tool_use_id, None)
                                if tool_info is None:
                                    continue

                                output = _extract_tool_result_text(block.get("content"))
                                tool_name = tool_info["name"]
                                tool_input = tool_info["input"]
                                command = tool_input.get("command") if tool_name == "Bash" else None

                                inv = ToolInvocation(
                                    conversation_id=conversation.conversation_id,
                                    provider="claude",
                                    timestamp=_parse_timestamp(tool_info["timestamp"]),
                                    tool_name=tool_name,
                                    command=command,
                                    arguments=tool_input if isinstance(tool_input, dict) else {},
                                    output=output,
                                    success=_check_success(output),
                                    skill_context=current_skill,
                                    conversation_summary=conversation_summary,
                                )
                                invocations.append(inv)
                                pending_next_action.append(inv)

                    elif isinstance(user_content, str):
                        # Plain text user message — may signal a new topic / reset skill context
                        text = user_content.strip()
                        if text and not text.startswith("<") and len(text) > 20:
                            # Heuristic: a substantial new user message likely changes context
                            current_skill = None

        return invocations
