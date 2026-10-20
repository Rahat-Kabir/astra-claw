"""CLI-only checks for shared output bounds and recovery through file pages."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from astra_claw.agent.events import AgentEvents
from astra_claw.agent.tool_output import MAX_BYTES, MAX_LINES, bound_tool_result
from astra_claw.agent.tool_runner import execute_tool_calls
from astra_claw.constants import get_astraclaw_home
from astra_claw.tools.file_tools import read_file


def test_small_result_is_unchanged_and_creates_no_artifacts():
    original = '{"output": "hello", "exit_code": 7}'
    assert bound_tool_result(original) == original
    assert not (get_astraclaw_home() / "tool-output").exists()


@pytest.mark.parametrize("text", ["x" * MAX_BYTES, "line\n" * MAX_LINES], ids=["bytes", "lines"])
def test_exact_limits_are_not_truncated(text):
    original = json.dumps({"output": text})
    assert bound_tool_result(original) == original


@pytest.mark.parametrize("field", ["output", "content", "summary"])
def test_line_limit_preserves_metadata_and_complete_text(field):
    text = "".join(f"line {i}\n" for i in range(1, 2202))
    result = json.loads(bound_tool_result(json.dumps({field: text, "exit_code": 9})))
    assert result["truncated"] is True
    assert result["exit_code"] == 9
    assert len(result[field].splitlines()) == MAX_LINES
    path = Path(result["output_path"])
    assert path.is_absolute()
    assert path.parent == (get_astraclaw_home() / "tool-output").resolve()
    assert path.read_text(encoding="utf-8") == text
    assert "read_file" in result["truncation_message"]
    recovered = json.loads(read_file({"path": str(path), "offset": 2001, "limit": 201}))
    assert recovered["content"] == "".join(text.splitlines(keepends=True)[2000:])
    assert recovered["next_offset"] is None


def test_byte_limit_handles_unicode_and_a_single_giant_line():
    text = "🙂" * 20000
    result = json.loads(bound_tool_result(json.dumps({"output": text})))
    assert len(result["output"].encode("utf-8")) <= MAX_BYTES
    assert result["output"] == text[:MAX_BYTES // 4]
    assert Path(result["output_path"]).read_text(encoding="utf-8") == text


def test_nested_result_is_bounded_and_saved_in_full():
    original = {"results": [{"text": "x" * MAX_BYTES}], "exit_code": 2}
    result = json.loads(bound_tool_result(json.dumps(original)))
    assert result["truncated"] is True
    assert result["exit_code"] == 2
    assert len(result["output"].encode("utf-8")) <= MAX_BYTES
    assert json.loads(Path(result["output_path"]).read_text(encoding="utf-8")) == original


def test_existing_tool_truncation_flag_does_not_bypass_shared_limit():
    result = json.loads(bound_tool_result(json.dumps({"output": "x" * (MAX_BYTES + 1), "truncated": True})))
    assert "output_path" in result


def test_large_metadata_uses_complete_document_instead_of_dropping_fields():
    original = {"output": "small", "other": "y" * 60000, "status": "failed", "error": "failure"}
    result = json.loads(bound_tool_result(json.dumps(original)))
    assert result["status"] == "failed"
    assert result["error"] == "failure"
    assert len(result["output"].encode("utf-8")) <= MAX_BYTES
    assert json.loads(Path(result["output_path"]).read_text(encoding="utf-8")) == original


def test_combined_byte_and_line_limits():
    text = ("🙂" * 100 + "\n") * 2100
    result = json.loads(bound_tool_result(json.dumps({"content": text})))
    assert len(result["content"].encode("utf-8")) <= MAX_BYTES
    assert len(result["content"].splitlines()) <= MAX_LINES


def test_cleanup_only_expires_owned_files(tmp_path):
    directory = get_astraclaw_home() / "tool-output"
    directory.mkdir(parents=True)
    expired = directory / ("tool_" + "a" * 32 + ".txt")
    recent = directory / ("tool_" + "b" * 32 + ".txt")
    unrelated = directory / "keep.txt"
    for path in (expired, recent, unrelated):
        path.write_text("saved", encoding="utf-8")
    old = time.time() - 8 * 24 * 60 * 60
    for path in (expired, unrelated):
        os.utime(path, (old, old))
    bound_tool_result(json.dumps({"output": "x" * (MAX_BYTES + 1)}))
    assert not expired.exists()
    assert recent.exists()
    assert unrelated.exists()


def test_spill_write_failure_propagates():
    with patch("astra_claw.agent.tool_output.atomic_write_text", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            bound_tool_result(json.dumps({"output": "x" * (MAX_BYTES + 1)}))


def test_runner_bounds_real_shell_output_before_events_and_history():
    # Real subprocess, no provider calls: also proves the shared dispatch boundary.
    seen = []
    # Use a short cross-platform command to avoid Windows command length limits.
    call = {"id": "shell-1", "function": {
        "name": "shell", "arguments": json.dumps({
            "command": subprocess.list2cmdline([sys.executable, "-c", "print('x' * 60000)"]),
        }),
    }}
    messages = execute_tool_calls([call], memory_store=None, events=AgentEvents(
        on_tool_complete=lambda *args: seen.append(args[-1]),
    ))
    payload = json.loads(messages[0]["content"])
    assert payload["exit_code"] == 0
    assert payload["truncated"] is True
    assert len(payload["output"].encode("utf-8")) <= MAX_BYTES
    assert len(Path(payload["output_path"]).read_text(encoding="utf-8")) == 60000
    assert seen == [messages[0]["content"]]
    assert messages[0]["tool_call_id"] == "shell-1"


def test_runner_bounds_special_case_tools_too():
    call = {"id": "clarify-1", "function": {
        "name": "clarify", "arguments": json.dumps({"question": "Which?"}),
    }}
    messages = execute_tool_calls([call], memory_store=None, clarify_callback=lambda *_: "x" * 60000)
    payload = json.loads(messages[0]["content"])
    assert payload["truncated"] is True
    original = json.loads(Path(payload["output_path"]).read_text(encoding="utf-8"))
    assert original["user_response"] == "x" * 60000
