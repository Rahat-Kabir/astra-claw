"""Shared path safety helpers for file-writing tools."""

import difflib
import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..constants import get_workspace_fence


BLOCKED_PATTERNS = [
    ".env",
    ".git",
    "credentials",
    "id_rsa",
    "id_ed25519",
    ".ssh",
    ".aws",
    ".gnupg",
]


def is_sensitive_path(filepath: Path) -> bool:
    """Return True when filepath targets a credential-like or protected path."""
    parts = filepath.resolve().parts
    name = filepath.name
    for pattern in BLOCKED_PATTERNS:
        if pattern == name or pattern in parts:
            return True
    return False


def is_write_blocked(filepath: Path) -> bool:
    """Return True when filepath targets a protected path."""
    return is_sensitive_path(filepath)


def inside_workspace_fence(filepath: Path) -> bool:
    """Return True when filepath resolves inside the active workspace fence."""
    fence = get_workspace_fence()
    try:
        resolved = filepath.resolve()
    except OSError:
        return False
    try:
        return resolved.is_relative_to(fence)
    except AttributeError:
        try:
            resolved.relative_to(fence)
            return True
        except ValueError:
            return False


def atomic_write_text(filepath: Path, content: str) -> int:
    """Atomically write text to filepath and return bytes written."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    encoded = content.encode("utf-8")
    fd, tmp_path = tempfile.mkstemp(
        dir=str(filepath.parent), suffix=".tmp", prefix=f".{filepath.name}."
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, filepath)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return len(encoded)


def unified_diff(old_content: str, new_content: str, path: str) -> str:
    """Return a unified diff for a file content change.

    Both sides are normalized to end with a newline so a source line lacking a
    trailing newline can't merge a '-' and '+' onto one physical line (which
    would render as a single mis-colored row). This only affects the displayed
    diff, never the bytes written.
    """
    if old_content and not old_content.endswith("\n"):
        old_content += "\n"
    if new_content and not new_content.endswith("\n"):
        new_content += "\n"
    return "".join(
        difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


# ---------------------------------------------------------------------------
# Write approval — optional preview-and-approve gate for file edits
# ---------------------------------------------------------------------------
#
# Mirrors shell_tool's approval pattern: a module-level callback set once by
# the interactive layer. When no callback is registered (one-shot mode,
# scripts, tests) writes proceed unchanged, so non-interactive callers never
# hang waiting for input nobody can give.

_write_approval_callback: Optional[Callable[[str, str, str], bool]] = None


def set_write_approval_callback(
    callback: Optional[Callable[[str, str, str], bool]],
) -> None:
    """Register (or clear with None) the file-write approval callback.

    The callback receives (path, diff, action) where action is "write" or
    "patch", and returns True to apply the change, False to reject it.
    """
    global _write_approval_callback
    _write_approval_callback = callback


def request_write_approval(path: str, diff: str, action: str) -> bool:
    """Return True if the write may proceed.

    No callback registered → allow (preserves non-interactive behavior).
    """
    if _write_approval_callback is None:
        return True
    return _write_approval_callback(path, diff, action)


# ---------------------------------------------------------------------------
# Undo stack — pre-write snapshots backing the /undo command
# ---------------------------------------------------------------------------
#
# Each successful write banks the file's pre-write state plus a hash of the
# content actually written. /undo verifies the file still matches that hash
# before restoring, so user edits made after the write are never clobbered.
# In-memory only: entries live for the current REPL session.

UNDO_STACK_LIMIT = 25


@dataclass
class UndoEntry:
    path: str
    old_content: str
    existed: bool
    written_hash: str


_undo_stack: list[UndoEntry] = []


@dataclass
class UndoResult:
    status: str  # "empty" | "restored" | "removed" | "already_gone"
    #            # | "refused_modified" | "refused_missing"
    #            # | "refused_unsafe" | "error"
    path: str
    detail: str = ""


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def record_undo(path: str, old_content: str, existed: bool, new_content: str) -> None:
    """Bank a completed write's inverse. Call only AFTER the write succeeded."""
    frozen_path = str(Path(path).expanduser().resolve())
    _undo_stack.append(
        UndoEntry(frozen_path, old_content, existed, _content_hash(new_content))
    )
    if len(_undo_stack) > UNDO_STACK_LIMIT:
        _undo_stack.pop(0)


def clear_undo() -> None:
    """Drop all undo entries (the REPL calls this at session start)."""
    _undo_stack.clear()


def undo_last_write() -> UndoResult:
    """Revert the most recent approved write, refusing on any uncertainty.

    Peeks the newest entry, verifies the file still holds the content Astra
    wrote, restores the pre-write state, and pops only on success — a failed
    undo keeps its entry so it can be retried.
    """
    if not _undo_stack:
        return UndoResult("empty", "")
    entry = _undo_stack[-1]
    target = Path(entry.path)
    if not inside_workspace_fence(target):
        return UndoResult(
            "refused_unsafe",
            entry.path,
            "path is outside the active workspace fence",
        )
    if is_write_blocked(target):
        return UndoResult(
            "refused_unsafe",
            entry.path,
            "path is protected",
        )
    try:
        if not target.exists():
            if entry.existed:
                return UndoResult(
                    "refused_missing", entry.path, "file is gone since the write"
                )
            _undo_stack.pop()
            return UndoResult("already_gone", entry.path)
        current = target.read_text(encoding="utf-8")
        if _content_hash(current) != entry.written_hash:
            return UndoResult(
                "refused_modified", entry.path, "file changed since the write"
            )
        if entry.existed:
            atomic_write_text(target, entry.old_content)
            status = "restored"
        else:
            target.unlink()
            status = "removed"
    except (OSError, UnicodeDecodeError) as exc:
        return UndoResult("error", entry.path, str(exc))
    _undo_stack.pop()
    return UndoResult(status, entry.path)
