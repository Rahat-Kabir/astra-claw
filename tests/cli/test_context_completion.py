import json
import os
from unittest.mock import patch

import pytest
from prompt_toolkit.document import Document

from astra_claw import constants
from astra_claw.cli.commands import AstraCompleter
from astra_claw.cli.context_completion import ContextReferenceCompleter


@pytest.fixture(autouse=True)
def _reset_fence():
    constants._workspace_fence = None
    yield
    constants._workspace_fence = None


def _completion_texts(completer, text: str) -> list[str]:
    return [completion.text for completion in completer.get_completions(Document(text), None)]


def test_at_root_suggests_reference_types(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    constants.set_workspace_fence(tmp_path)

    texts = _completion_texts(ContextReferenceCompleter(), "@")

    assert texts == ["@file:", "@folder:", "@diff", "@session:"]


def test_at_root_suggests_inside_normal_prompt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    constants.set_workspace_fence(tmp_path)

    texts = _completion_texts(ContextReferenceCompleter(), "review @")

    assert "@file:" in texts
    assert "@folder:" in texts


def test_file_completion_suggests_matching_files_and_folders(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    constants.set_workspace_fence(tmp_path)
    (tmp_path / "README.md").write_text("hi", encoding="utf-8")
    (tmp_path / "reports").mkdir()

    texts = _completion_texts(ContextReferenceCompleter(), "@file:R")

    assert "@file:README.md" in texts
    assert "@file:reports/" in texts


def test_folder_completion_suggests_only_matching_folders(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    constants.set_workspace_fence(tmp_path)
    (tmp_path / "astra_claw").mkdir()
    (tmp_path / "astra_notes.txt").write_text("hi", encoding="utf-8")

    texts = _completion_texts(ContextReferenceCompleter(), "@folder:astra")

    assert "@folder:astra_claw/" in texts
    assert "@folder:astra_notes.txt" not in texts


def test_completion_skips_hidden_and_sensitive_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    constants.set_workspace_fence(tmp_path)
    (tmp_path / ".env").write_text("SECRET=x", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / "safe.txt").write_text("ok", encoding="utf-8")

    texts = _completion_texts(ContextReferenceCompleter(), "@file:")

    assert "@file:safe.txt" in texts
    assert "@file:.env" not in texts
    assert "@file:.git/" not in texts


def test_nested_file_completion(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    constants.set_workspace_fence(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("print('hi')", encoding="utf-8")

    texts = _completion_texts(ContextReferenceCompleter(), "@file:src/m")

    assert "@file:src/main.py" in texts


def test_fuzzy_file_completion_finds_nested_matches(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    constants.set_workspace_fence(tmp_path)
    nested = tmp_path / "astra_claw" / "cli"
    nested.mkdir(parents=True)
    (nested / "repl.py").write_text("print('hi')", encoding="utf-8")

    texts = _completion_texts(ContextReferenceCompleter(), "@file:repl")

    assert "@file:astra_claw/cli/repl.py" in texts


def test_fuzzy_folder_completion_finds_nested_matches(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    constants.set_workspace_fence(tmp_path)
    nested = tmp_path / "docs" / "guides"
    nested.mkdir(parents=True)

    texts = _completion_texts(ContextReferenceCompleter(), "@folder:guide")

    assert "@folder:docs/guides/" in texts


def test_session_completion_matches_title(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    constants.set_workspace_fence(tmp_path)
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "2026-05-13_abcd1234.jsonl").write_text(
        json.dumps(
            {
                "type": "meta",
                "id": "2026-05-13_abcd1234",
                "created": "2026-05-13T00:00:00",
                "title": "Context Refs",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
        texts = _completion_texts(ContextReferenceCompleter(), "@session:context")

    assert "@session:2026-05-13_abcd1234" in texts


def test_fuzzy_results_are_capped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    constants.set_workspace_fence(tmp_path)
    for index in range(30):
        (tmp_path / f"file_{index:02d}_match.txt").write_text("x", encoding="utf-8")

    texts = _completion_texts(ContextReferenceCompleter(), "@file:match")

    assert len(texts) <= 25


def test_session_completion_suggests_recent_sessions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    constants.set_workspace_fence(tmp_path)
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "2026-05-13_abcd1234.jsonl").write_text(
        json.dumps(
            {
                "type": "meta",
                "id": "2026-05-13_abcd1234",
                "created": "2026-05-13T00:00:00",
                "title": "Context Refs",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
        texts = _completion_texts(ContextReferenceCompleter(), "@session:2026")

    assert "@session:2026-05-13_abcd1234" in texts


def test_completion_ignores_email_like_text(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    constants.set_workspace_fence(tmp_path)

    texts = _completion_texts(ContextReferenceCompleter(), "me@example.com")

    assert texts == []


def test_astra_completer_keeps_slash_commands_and_context_refs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    constants.set_workspace_fence(tmp_path)

    completer = AstraCompleter()

    assert "/help" in _completion_texts(completer, "/he")
    assert "@file:" in _completion_texts(completer, "@")
