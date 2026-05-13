import os
import subprocess
from unittest.mock import patch

import pytest

from astra_claw import constants
from astra_claw.cli.context_refs import expand_context_references


@pytest.fixture(autouse=True)
def _reset_fence():
    constants._workspace_fence = None
    yield
    constants._workspace_fence = None


def _set_workspace(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    constants.set_workspace_fence(tmp_path)


def test_no_refs_returns_original_message():
    message = "review the project"

    assert expand_context_references(message) == message


def test_file_ref_attaches_file_content(tmp_path, monkeypatch):
    _set_workspace(monkeypatch, tmp_path)
    (tmp_path / "note.txt").write_text("hello\nworld\n", encoding="utf-8")

    expanded = expand_context_references("Read @file:note.txt")

    assert "--- Attached Context ---" in expanded
    assert "## @file:note.txt" in expanded
    assert "hello\nworld" in expanded


def test_file_ref_line_range_attaches_only_selected_lines(tmp_path, monkeypatch):
    _set_workspace(monkeypatch, tmp_path)
    (tmp_path / "note.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")

    expanded = expand_context_references("Read @file:note.txt:2-3")

    assert "Lines: 2-3" in expanded
    assert "two\nthree" in expanded
    assert "one\n" not in expanded


def test_file_ref_strips_trailing_punctuation(tmp_path, monkeypatch):
    _set_workspace(monkeypatch, tmp_path)
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")

    expanded = expand_context_references("Read @file:note.txt, please")

    assert "## @file:note.txt" in expanded
    assert "hello" in expanded


def test_missing_file_becomes_warning(tmp_path, monkeypatch):
    _set_workspace(monkeypatch, tmp_path)

    expanded = expand_context_references("Read @file:missing.txt")

    assert "[WARNING: file not found]" in expanded


def test_sensitive_file_is_blocked(tmp_path, monkeypatch):
    _set_workspace(monkeypatch, tmp_path)
    (tmp_path / ".env").write_text("SECRET=x", encoding="utf-8")

    expanded = expand_context_references("Read @file:.env")

    assert "sensitive or protected path" in expanded
    assert "SECRET=x" not in expanded


def test_outside_workspace_file_is_blocked(tmp_path, monkeypatch):
    inside = tmp_path / "inside"
    outside = tmp_path / "outside"
    inside.mkdir()
    outside.mkdir()
    monkeypatch.chdir(inside)
    constants.set_workspace_fence(inside)
    target = outside / "note.txt"
    target.write_text("outside", encoding="utf-8")

    expanded = expand_context_references(f"Read @file:{target}")

    assert "outside the workspace fence" in expanded
    assert "```text\noutside" not in expanded


def test_binary_file_is_rejected(tmp_path, monkeypatch):
    _set_workspace(monkeypatch, tmp_path)
    (tmp_path / "data.bin").write_bytes(b"abc\x00def")

    expanded = expand_context_references("Read @file:data.bin")

    assert "binary or non-UTF-8" in expanded or "binary files are not supported" in expanded


def test_folder_ref_lists_tree_and_skips_ignored_dirs(tmp_path, monkeypatch):
    _set_workspace(monkeypatch, tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')", encoding="utf-8")
    (tmp_path / "src" / "__pycache__").mkdir()
    (tmp_path / "src" / "__pycache__" / "app.pyc").write_bytes(b"x")

    expanded = expand_context_references("Inspect @folder:src")

    assert "- app.py" in expanded
    assert "__pycache__" not in expanded


def test_diff_ref_attaches_git_diff(tmp_path, monkeypatch):
    _set_workspace(monkeypatch, tmp_path)

    fake_result = subprocess.CompletedProcess(
        args=["git"],
        returncode=0,
        stdout="diff --git a/a.txt b/a.txt\n+hello\n",
        stderr="",
    )
    with patch("astra_claw.cli.context_refs.subprocess.run", return_value=fake_result):
        expanded = expand_context_references("Review @diff")

    assert "```diff" in expanded
    assert "+hello" in expanded


def test_session_ref_attaches_session_transcript(tmp_path, monkeypatch):
    _set_workspace(monkeypatch, tmp_path)
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "old.jsonl").write_text(
        '{"type":"meta","id":"old","created":"2026-05-13T00:00:00"}\n'
        '{"role":"user","content":"debug auth","ts":"x"}\n'
        '{"role":"assistant","content":"fixed auth","ts":"x"}\n',
        encoding="utf-8",
    )

    with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
        expanded = expand_context_references("Recall @session:old")

    assert "USER:\ndebug auth" in expanded
    assert "ASSISTANT:\nfixed auth" in expanded


def test_current_session_ref_is_rejected(tmp_path, monkeypatch):
    _set_workspace(monkeypatch, tmp_path)

    expanded = expand_context_references(
        "Recall @session:current",
        current_session_id="current",
    )

    assert "current session cannot be attached to itself" in expanded


def test_total_context_cap_stops_expansion(tmp_path, monkeypatch):
    _set_workspace(monkeypatch, tmp_path)
    (tmp_path / "big.txt").write_text("x" * 1000, encoding="utf-8")

    expanded = expand_context_references("Read @file:big.txt", max_total_chars=300)

    assert "context reference budget exhausted" in expanded
