"""Shared path safety helpers for file-writing tools."""

import difflib
import os
import tempfile
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
