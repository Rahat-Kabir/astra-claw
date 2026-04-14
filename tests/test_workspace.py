"""Tests for workspace fence: --workspace flag + write_file jail."""

import json
import os
from pathlib import Path

import pytest

from astra_claw import constants
from astra_claw.__main__ import _apply_workspace_flag
from astra_claw.tools.file_tools import write_file


@pytest.fixture(autouse=True)
def _reset_fence():
    """Ensure each test starts with no active fence."""
    constants._workspace_fence = None
    yield
    constants._workspace_fence = None


def test_write_inside_fence_succeeds(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    constants.set_workspace_fence(tmp_path)

    result = json.loads(write_file({"path": "hello.txt", "content": "hi"}))

    assert "error" not in result
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hi"


def test_write_with_relative_escape_is_blocked(tmp_path, monkeypatch):
    inside = tmp_path / "inside"
    inside.mkdir()
    monkeypatch.chdir(inside)
    constants.set_workspace_fence(inside)

    result = json.loads(write_file({"path": "../escape.txt", "content": "pwned"}))

    assert "error" in result
    assert "escapes workspace fence" in result["error"]
    assert not (tmp_path / "escape.txt").exists()


def test_write_with_absolute_outside_fence_is_blocked(tmp_path, monkeypatch):
    inside = tmp_path / "inside"
    outside = tmp_path / "outside"
    inside.mkdir()
    outside.mkdir()
    monkeypatch.chdir(inside)
    constants.set_workspace_fence(inside)

    target = outside / "pwned.txt"
    result = json.loads(write_file({"path": str(target), "content": "x"}))

    assert "error" in result
    assert "escapes workspace fence" in result["error"]
    assert not target.exists()


def test_write_without_fence_falls_back_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # _workspace_fence stays None via the autouse fixture.

    result = json.loads(write_file({"path": "note.txt", "content": "ok"}))

    assert "error" not in result
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "ok"


def test_apply_workspace_flag_sets_fence_and_chdir(tmp_path):
    original_cwd = Path.cwd()
    argv = ["astra_claw", "--workspace", str(tmp_path), "hello"]

    try:
        result = _apply_workspace_flag(argv)
        assert result == tmp_path.resolve()
        assert Path.cwd() == tmp_path.resolve()
        assert constants.get_workspace_fence() == tmp_path.resolve()
        # Flag + value removed so downstream parsing stays clean.
        assert argv == ["astra_claw", "hello"]
    finally:
        os.chdir(original_cwd)


def test_apply_workspace_flag_rejects_missing_path(tmp_path):
    bogus = tmp_path / "does_not_exist"
    argv = ["astra_claw", "--workspace", str(bogus)]

    with pytest.raises(SystemExit) as exc:
        _apply_workspace_flag(argv)
    assert exc.value.code == 2


def test_apply_workspace_flag_absent_returns_none():
    argv = ["astra_claw", "hello"]
    assert _apply_workspace_flag(argv) is None
    assert argv == ["astra_claw", "hello"]
