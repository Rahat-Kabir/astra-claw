"""Unit tests for the pure tool-display helpers."""

import json

from astra_claw.cli.tool_display import (
    build_tool_preview,
    summarize_tool_result,
)


class TestBuildToolPreview:
    def test_path_based_tools_use_path(self):
        for name in ("read_file", "write_file", "patch"):
            assert build_tool_preview(name, {"path": "src/foo.py"}) == "src/foo.py"

    def test_shell_uses_command_and_collapses_whitespace(self):
        assert (
            build_tool_preview("shell", {"command": "pytest    -q\n  tests/"})
            == "pytest -q tests/"
        )

    def test_shell_truncates_long_commands(self):
        long_cmd = "echo " + "x" * 200
        out = build_tool_preview("shell", {"command": long_cmd})
        assert out.endswith("...")
        assert len(out) <= 60

    def test_search_files_uses_pattern_first_then_name(self):
        assert build_tool_preview("search_files", {"pattern": "TODO"}) == "TODO"
        assert build_tool_preview("search_files", {"name": "*.py"}) == "*.py"

    def test_memory_combines_action_and_target(self):
        assert (
            build_tool_preview("memory", {"action": "add", "target": "user"})
            == "add user"
        )

    def test_unknown_tool_falls_back_to_common_keys(self):
        assert build_tool_preview("weird_tool", {"query": "hello"}) == "hello"

    def test_missing_args_returns_empty_string(self):
        assert build_tool_preview("read_file", {}) == ""
        assert build_tool_preview("shell", None) == ""


class TestSummarizeToolResult:
    def test_error_payload_returns_error_prefix(self):
        result = json.dumps({"error": "something broke"})
        assert summarize_tool_result("read_file", result) == "error: something broke"

    def test_read_file_reports_line_count(self):
        result = json.dumps({"content": "a\nb\nc"})
        assert summarize_tool_result("read_file", result) == "3 lines"

    def test_write_file_reports_bytes(self):
        result = json.dumps({"bytes_written": 2048})
        assert summarize_tool_result("write_file", result) == "wrote 2.0 KB"

    def test_patch_counts_plus_minus_ignoring_headers(self):
        diff = "--- a/x\n+++ b/x\n-old line\n+new line\n+another\n"
        result = json.dumps({"success": True, "diff": diff})
        assert summarize_tool_result("patch", result) == "+2 -1"

    def test_search_files_reports_match_count(self):
        result = json.dumps({"matches": ["a:1:x", "b:2:y"], "total_count": 2})
        assert summarize_tool_result("search_files", result) == "2 matches"

    def test_search_files_singular_when_one_match(self):
        result = json.dumps({"matches": ["a:1:x"], "total_count": 1})
        assert summarize_tool_result("search_files", result) == "1 match"

    def test_shell_shows_exit_and_first_line(self):
        result = json.dumps({"exit_code": 0, "output": "hello\nworld"})
        assert summarize_tool_result("shell", result) == "exit 0 - hello"

    def test_shell_exit_only_when_no_output(self):
        result = json.dumps({"exit_code": 1, "output": ""})
        assert summarize_tool_result("shell", result) == "exit 1"

    def test_memory_success_returns_ok(self):
        result = json.dumps({"success": True})
        assert summarize_tool_result("memory", result) == "ok"

    def test_non_json_result_is_truncated_oneline(self):
        assert summarize_tool_result("shell", "plain text") == "plain text"
        assert summarize_tool_result("shell", "") is None

    def test_unknown_tool_with_json_returns_none(self):
        result = json.dumps({"random": "payload"})
        assert summarize_tool_result("weird_tool", result) is None
