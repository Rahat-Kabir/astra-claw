"""Tests for the /undo stack and undo_last_write restore semantics."""

import json
from pathlib import Path

import pytest

from astra_claw import constants
from astra_claw.tools import path_safety
from astra_claw.tools.file_tools import write_file
from astra_claw.tools.patch_tool import patch_file


@pytest.fixture(autouse=True)
def _fence_and_stack(tmp_path, monkeypatch):
    """Each test runs inside tmp_path with an empty undo stack."""
    monkeypatch.chdir(tmp_path)
    constants.set_workspace_fence(tmp_path)
    path_safety.set_write_approval_callback(None)
    path_safety.clear_undo()
    yield
    constants._workspace_fence = None
    path_safety.set_write_approval_callback(None)
    path_safety.clear_undo()


def _approve():
    path_safety.set_write_approval_callback(lambda *_: True)


# ---------------------------------------------------------------------------
# Stack mechanics
# ---------------------------------------------------------------------------

def test_record_and_pop_are_lifo(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("new-a", encoding="utf-8")
    b.write_text("new-b", encoding="utf-8")
    path_safety.record_undo(str(a), "old-a", True, "new-a")
    path_safety.record_undo(str(b), "old-b", True, "new-b")

    result = path_safety.undo_last_write()
    assert (result.status, result.path) == ("restored", str(b))
    assert b.read_text(encoding="utf-8") == "old-b"

    result = path_safety.undo_last_write()
    assert (result.status, result.path) == ("restored", str(a))
    assert a.read_text(encoding="utf-8") == "old-a"


def test_undo_last_write_empty_stack():
    assert path_safety.undo_last_write().status == "empty"


def test_stack_limit_evicts_oldest(monkeypatch):
    monkeypatch.setattr(path_safety, "UNDO_STACK_LIMIT", 3)
    for i in range(5):
        path = Path(f"f{i}.txt")
        path.write_text("new", encoding="utf-8")
        path_safety.record_undo(str(path), "old", True, "new")

    assert len(path_safety._undo_stack) == 3
    assert path_safety._undo_stack[0].path.endswith("f2.txt")


def test_clear_undo_empties_stack():
    path_safety.record_undo("a.txt", "old", True, "new")
    path_safety.clear_undo()

    assert path_safety.undo_last_write().status == "empty"


def test_record_undo_freezes_relative_path(tmp_path, monkeypatch):
    target = tmp_path / "note.txt"
    target.write_text("new", encoding="utf-8")
    path_safety.record_undo("note.txt", "old", True, "new")

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    decoy = elsewhere / "note.txt"
    decoy.write_text("new", encoding="utf-8")
    monkeypatch.chdir(elsewhere)

    result = path_safety.undo_last_write()

    assert result.status == "restored"
    assert target.read_text(encoding="utf-8") == "old"
    assert decoy.read_text(encoding="utf-8") == "new"


# ---------------------------------------------------------------------------
# undo_last_write outcomes
# ---------------------------------------------------------------------------

def test_undo_restores_previous_content(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("old", encoding="utf-8")
    path_safety.record_undo(str(target), "old", True, "new")
    target.write_text("new", encoding="utf-8")

    result = path_safety.undo_last_write()

    assert result.status == "restored"
    assert target.read_text(encoding="utf-8") == "old"
    assert path_safety.undo_last_write().status == "empty"


def test_undo_removes_created_file(tmp_path):
    target = tmp_path / "created.txt"
    target.write_text("new", encoding="utf-8")
    path_safety.record_undo(str(target), "", False, "new")

    result = path_safety.undo_last_write()

    assert result.status == "removed"
    assert not target.exists()


def test_undo_refuses_when_file_changed_after_write(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("old", encoding="utf-8")
    path_safety.record_undo(str(target), "old", True, "new")
    target.write_text("new", encoding="utf-8")
    target.write_text("user hand-edit", encoding="utf-8")

    result = path_safety.undo_last_write()

    assert result.status == "refused_modified"
    assert target.read_text(encoding="utf-8") == "user hand-edit"
    # Entry retained: fixing the file by hand makes the same undo succeed.
    target.write_text("new", encoding="utf-8")
    assert path_safety.undo_last_write().status == "restored"


def test_undo_refuses_missing_file_but_keeps_entry(tmp_path):
    target = tmp_path / "note.txt"
    path_safety.record_undo(str(target), "old", True, "new")

    result = path_safety.undo_last_write()

    assert result.status == "refused_missing"
    assert len(path_safety._undo_stack) == 1


def test_undo_created_file_already_gone_is_noop_and_pops(tmp_path):
    target = tmp_path / "created.txt"
    path_safety.record_undo(str(target), "", False, "new")

    result = path_safety.undo_last_write()

    assert result.status == "already_gone"
    assert path_safety.undo_last_write().status == "empty"


def test_failed_restore_keeps_entry(tmp_path, monkeypatch):
    target = tmp_path / "note.txt"
    target.write_text("new", encoding="utf-8")
    path_safety.record_undo(str(target), "old", True, "new")

    def boom(filepath, content):
        raise OSError("disk on fire")

    monkeypatch.setattr(path_safety, "atomic_write_text", boom)

    result = path_safety.undo_last_write()

    assert result.status == "error"
    assert "disk on fire" in result.detail
    assert target.read_text(encoding="utf-8") == "new"
    assert len(path_safety._undo_stack) == 1


def test_undo_binary_replacement_refuses(tmp_path):
    target = tmp_path / "note.bin"
    target.write_text("old", encoding="utf-8")
    path_safety.record_undo(str(target), "old", True, "new")
    target.write_bytes(b"\xff\xfe\x00binary")

    result = path_safety.undo_last_write()

    assert result.status == "error"
    assert len(path_safety._undo_stack) == 1


def test_undo_rechecks_workspace_fence(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("new", encoding="utf-8")
    path_safety.record_undo(str(target), "old", True, "new")
    other_workspace = tmp_path / "other"
    other_workspace.mkdir()
    constants.set_workspace_fence(other_workspace)

    result = path_safety.undo_last_write()

    assert result.status == "refused_unsafe"
    assert "workspace fence" in result.detail
    assert target.read_text(encoding="utf-8") == "new"
    assert len(path_safety._undo_stack) == 1


# ---------------------------------------------------------------------------
# write_file integration
# ---------------------------------------------------------------------------

def test_write_file_records_undo_for_existing_file(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("old", encoding="utf-8")
    _approve()

    result = json.loads(write_file({"path": "note.txt", "content": "new"}))

    assert "error" not in result
    assert path_safety.undo_last_write().status == "restored"
    assert target.read_text(encoding="utf-8") == "old"


def test_write_file_new_file_undo_deletes(tmp_path):
    _approve()

    result = json.loads(write_file({"path": "fresh.txt", "content": "hello"}))

    assert "error" not in result
    assert path_safety.undo_last_write().status == "removed"
    assert not (tmp_path / "fresh.txt").exists()


def test_write_file_rejection_records_nothing(tmp_path):
    path_safety.set_write_approval_callback(lambda *_: False)

    write_file({"path": "new.txt", "content": "hello"})

    assert path_safety._undo_stack == []


def test_write_file_failed_write_records_nothing(tmp_path, monkeypatch):
    target = tmp_path / "note.txt"
    target.write_text("old", encoding="utf-8")
    _approve()

    def boom(filepath, content):
        raise OSError("disk full")

    monkeypatch.setattr(
        "astra_claw.tools.file_tools.atomic_write_text", boom
    )

    result = json.loads(write_file({"path": "note.txt", "content": "new"}))

    assert "Failed to write file" in result["error"]
    assert target.read_text(encoding="utf-8") == "old"
    assert path_safety._undo_stack == []


def test_write_file_unreadable_existing_file_errors(tmp_path, monkeypatch):
    target = tmp_path / "locked.txt"
    target.write_text("secret", encoding="utf-8")
    _approve()

    def unreadable(self, *args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_text", unreadable)

    result = json.loads(write_file({"path": "locked.txt", "content": "x"}))

    assert "Cannot read existing file" in result["error"]
    assert target.read_bytes() == b"secret"
    assert path_safety._undo_stack == []


# ---------------------------------------------------------------------------
# patch integration
# ---------------------------------------------------------------------------

def test_patch_records_undo(tmp_path):
    target = tmp_path / "code.py"
    target.write_text("value = 1\n", encoding="utf-8")
    _approve()

    result = json.loads(
        patch_file({"path": "code.py", "old_text": "value = 1", "new_text": "value = 2"})
    )

    assert result["success"] is True
    assert path_safety.undo_last_write().status == "restored"
    assert target.read_text(encoding="utf-8") == "value = 1\n"


def test_patch_rejection_records_nothing(tmp_path):
    target = tmp_path / "code.py"
    target.write_text("value = 1\n", encoding="utf-8")
    path_safety.set_write_approval_callback(lambda *_: False)

    patch_file({"path": "code.py", "old_text": "value = 1", "new_text": "value = 2"})

    assert path_safety._undo_stack == []


# ---------------------------------------------------------------------------
# Chained undos on the same file
# ---------------------------------------------------------------------------

def test_chained_writes_undo_step_by_step(tmp_path):
    target = tmp_path / "log.txt"
    target.write_text("v1", encoding="utf-8")
    _approve()
    write_file({"path": "log.txt", "content": "v2"})
    write_file({"path": "log.txt", "content": "v3"})

    assert path_safety.undo_last_write().status == "restored"
    assert target.read_text(encoding="utf-8") == "v2"
    assert path_safety.undo_last_write().status == "restored"
    assert target.read_text(encoding="utf-8") == "v1"
