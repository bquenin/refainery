"""Tool name normalization across providers.

Maps provider-specific tool names to canonical names so that detection
and analysis stages operate on provider-agnostic data.
"""

from __future__ import annotations

# Cursor tool names → canonical names (from mnemonai tool_format.rs)
CURSOR_TOOL_MAP: dict[str, str] = {
    # Terminal
    "run_terminal_cmd": "Bash",
    "run_terminal_command_v2": "Bash",
    # Read
    "read_file": "Read",
    "read_file_v2": "Read",
    # Edit
    "edit_file": "Edit",
    "edit_file_v2": "Edit",
    "edit_file_v2_search_replace": "Edit",
    "edit_file_v2_apply_based": "Edit",
    "edit_file_v2_write": "Edit",
    "search_replace": "Edit",
    "apply_patch": "Edit",
    "MultiEdit": "Edit",
    # Search / Grep
    "grep": "Grep",
    "grep_search": "Grep",
    "rg": "Grep",
    "ripgrep": "Grep",
    "ripgrep_raw_search": "Grep",
    "codebase_search": "Grep",
    "semantic_search_full": "Grep",
    # List / Glob
    "list_dir": "List",
    "list_dir_v2": "List",
    "glob_file_search": "Glob",
    "file_search": "Glob",
    # Write
    "write": "Write",
    "delete_file": "Write",
    # Web
    "web_fetch": "WebFetch",
    "web_search": "WebSearch",
    # Task
    "task_v2": "Task",
    "create_plan": "Task",
}


def normalize_tool_name(provider: str, raw_name: str) -> str:
    """Normalize a tool name to its canonical form.

    Claude Code tool names are already canonical (Bash, Read, Edit, etc.).
    Cursor tool names are mapped via CURSOR_TOOL_MAP.
    Unknown tool names are passed through unchanged.
    """
    if provider == "cursor":
        return CURSOR_TOOL_MAP.get(raw_name, raw_name)
    return raw_name
