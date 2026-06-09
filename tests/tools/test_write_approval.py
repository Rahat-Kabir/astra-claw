"""Tests for preview-and-approve gating of write_file / patch."""

import json

import pytest

from astra_claw import constants
from astra_claw.tools import path_safety
from astra_claw.tools.file_tools import write_file
from astra_claw.tools.patch_tool import patch_file


@pytest.fixture(autouse=True)
def _fence_and_callback(tmp_path, monkeypatch):
    """Each test runs inside tmp_path with no leaked approval callback."""
    monkeypatch.chdir(tmp_path)
    constants.set_workspace_fence(tmp_path)
    path_safety.set_write_approval_callback(None)
    yield
    constants._workspace_fence = None
    path_safety.set_write_approval_callback(None)


# ---------------------------------------------------------------------------
# request_write_approval — the default-allow contract
# ---------------------------------------------------------------------------

def test_request_write_approval_allows_when_no_callback():
    assert path_safety.request_write_approval("x.txt", "diff", "write") is True


def test_request_write_approval_consults_callback():
    seen = {}

    def cb(path, diff, action):
        seen["args"] = (path, diff, action)
        return False

    path_safety.set_write_approval_callback(cb)
    assert path_safety.request_write_approval("x.txt", "the-diff", "patch") is False
    assert seen["args"] == ("x.txt", "the-diff", "patch")


def test_unified_diff_no_trailing_newline_does_not_merge_lines():
    # Original last line has no trailing newline; appending content must not
    # glue a '-' and '+' onto one physical line.
    old = "# Title\n\nA brief description."          # no trailing \n
    new = "# Title\n\nA brief description.\n\nMore.\n"

    diff = path_safety.unified_diff(old, new, "README.md")

    for line in diff.splitlines():
        # No line may contain both a removal and an addition marker.
        assert not (line.startswith("-") and "+" in line[1:] and "A brief" in line)
    # The unchanged description line should stay context (space prefix), not "-".
    assert "-A brief description." not in diff
    assert "+More." in diff


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------

def test_write_file_rejected_does_not_write(tmp_path):
    path_safety.set_write_approval_callback(lambda *_: False)

    result = json.loads(write_file({"path": "new.txt", "content": "hello"}))

    assert result["status"] == "rejected_by_user"
    assert not (tmp_path / "new.txt").exists()


def test_write_file_approved_writes(tmp_path):
    path_safety.set_write_approval_callback(lambda *_: True)

    result = json.loads(write_file({"path": "new.txt", "content": "hello"}))

    assert "error" not in result
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "hello"


def test_write_file_callback_receives_diff(tmp_path):
    captured = {}

    def cb(path, diff, action):
        captured["diff"] = diff
        captured["action"] = action
        return True

    path_safety.set_write_approval_callback(cb)
    write_file({"path": "note.txt", "content": "line one\n"})

    assert captured["action"] == "write"
    assert "+line one" in captured["diff"]


# ---------------------------------------------------------------------------
# patch
# ---------------------------------------------------------------------------

def test_patch_rejected_leaves_file_unchanged(tmp_path):
    target = tmp_path / "code.py"
    target.write_text("value = 1\n", encoding="utf-8")
    path_safety.set_write_approval_callback(lambda *_: False)

    result = json.loads(
        patch_file({"path": "code.py", "old_text": "value = 1", "new_text": "value = 2"})
    )

    assert result["status"] == "rejected_by_user"
    assert target.read_text(encoding="utf-8") == "value = 1\n"


def test_patch_approved_applies(tmp_path):
    target = tmp_path / "code.py"
    target.write_text("value = 1\n", encoding="utf-8")
    path_safety.set_write_approval_callback(lambda *_: True)

    result = json.loads(
        patch_file({"path": "code.py", "old_text": "value = 1", "new_text": "value = 2"})
    )

    assert result["success"] is True
    assert target.read_text(encoding="utf-8") == "value = 2\n"


# ---------------------------------------------------------------------------
# REPL "always" latch
# ---------------------------------------------------------------------------

def test_build_write_approval_always_latch():
    from astra_claw.cli.repl import _build_write_approval_callback
    from astra_claw.cli.ui import CliUI

    answers = iter(["a"])  # one "always", then it must never prompt again

    class FakePrompt:
        def prompt(self, *_args, **_kwargs):
            return next(answers)

    cb = _build_write_approval_callback(CliUI(), FakePrompt())

    assert cb("f.py", "diff", "write") is True   # consumes "a", latches
    assert cb("g.py", "diff", "write") is True   # no prompt available → latch holds
