"""Shared constants for Astra-Claw.

Import-safe module with no dependencies — can be imported from anywhere
without risk of circular imports.
"""

import os
from pathlib import Path


def get_astraclaw_home() -> Path:
    """Return the Astra-Claw home directory (default: ~/.astraclaw).

    Reads ASTRACLAW_HOME env var, falls back to ~/.astraclaw.
    This is the single source of truth — all other modules should import this.
    """
    return Path(os.getenv("ASTRACLAW_HOME", Path.home() / ".astraclaw"))
