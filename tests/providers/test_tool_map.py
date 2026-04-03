"""Tests for tool name normalization."""

from refainery.providers.tool_map import normalize_tool_name


class TestNormalization:
    def test_claude_tools_pass_through(self):
        for name in ("Bash", "Read", "Edit", "Grep", "Glob", "Write", "WebFetch", "WebSearch", "Task"):
            assert normalize_tool_name("claude", name) == name

    def test_cursor_terminal_tools(self):
        assert normalize_tool_name("cursor", "run_terminal_cmd") == "Bash"
        assert normalize_tool_name("cursor", "run_terminal_command_v2") == "Bash"

    def test_cursor_read_tools(self):
        assert normalize_tool_name("cursor", "read_file") == "Read"
        assert normalize_tool_name("cursor", "read_file_v2") == "Read"

    def test_cursor_edit_tools(self):
        for name in ("edit_file", "edit_file_v2", "search_replace", "apply_patch", "MultiEdit"):
            assert normalize_tool_name("cursor", name) == "Edit"

    def test_cursor_search_tools(self):
        for name in ("grep", "grep_search", "rg", "ripgrep", "codebase_search"):
            assert normalize_tool_name("cursor", name) == "Grep"

    def test_unknown_tools_pass_through(self):
        assert normalize_tool_name("cursor", "some_new_tool") == "some_new_tool"
        assert normalize_tool_name("claude", "CustomTool") == "CustomTool"
