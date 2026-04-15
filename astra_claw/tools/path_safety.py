"""Shared path safety helpers for file-writing tools."""

import os
import tempfile
from pathlib import Path

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


def is_write_blocked(filepath: Path) -> bool:
    """Return True when filepath targets a protected path."""
    parts = filepath.resolve().parts
    name = filepath.name
    for pattern in BLOCKED_PATTERNS:
        if pattern == name or pattern in parts:
            return True
    return False


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
