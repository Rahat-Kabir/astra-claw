"""Shared constants for Astra-Claw.

Import-safe module with no dependencies — can be imported from anywhere
without risk of circular imports.
"""

import os
from pathlib import Path
from typing import Optional


def get_astraclaw_home() -> Path:
    """Return the Astra-Claw home directory (default: ~/.astraclaw).

    Reads ASTRACLAW_HOME env var, falls back to ~/.astraclaw.
    This is the single source of truth — all other modules should import this.
    """
    configured = os.getenv("ASTRACLAW_HOME")
    if configured:
        return Path(configured)
    return Path.home() / ".astraclaw"


# ---------------------------------------------------------------------------
# Workspace fence — locks write_file to a single directory tree.
# Unset by default; __main__.py sets it when --workspace is passed.
# ---------------------------------------------------------------------------

_workspace_fence: Optional[Path] = None


def set_workspace_fence(path: Path) -> None:
    global _workspace_fence
    _workspace_fence = Path(path).resolve()


def get_workspace_fence() -> Path:
    """Return the active workspace fence, or the current cwd when unset."""
    if _workspace_fence is not None:
        return _workspace_fence
    return Path.cwd().resolve()
