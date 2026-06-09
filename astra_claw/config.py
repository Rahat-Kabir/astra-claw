"""Configuration for Astra-Claw.

Handles:
- Creating ~/.astraclaw/ directory structure on first run
- Loading config.yaml with sane defaults
- Deep merging user overrides on top of defaults
- Persisting partial user overrides back to config.yaml
"""

import copy
import os
import tempfile
from pathlib import Path
from typing import Any, Dict

import yaml

from .constants import get_astraclaw_home
from .soul import ensure_default_soul_md


DEFAULT_CONFIG: Dict[str, Any] = {
    "model": {
        "default": "gpt-5.4-mini",
        "provider": "openai",
        "fallback_provider": "openrouter",
        "fallback_model": "gpt-5.4-mini",
        "context_window": 128000,
    },
    "agent": {
        "max_turns": 20,
    },
    "compression": {
        "enabled": True,
        "threshold_ratio": 0.80,
        "reserve_tokens": 4000,
        "keep_first_n": 2,
        "keep_last_n": 6,
        "max_passes": 2,
        "summary_model": None,
    },
    "memory": {
        "enabled": True,
        "user_profile_enabled": True,
        "memory_char_limit": 2200,
        "user_char_limit": 1375,
    },
    "session": {
        "auto_title": True,
    },
    "cli": {
        "render_markdown": False,
        "confirm_edits": True,
    },
}


def ensure_astraclaw_home() -> Path:
    """Create ~/.astraclaw/ and subdirs on first run. Returns the home path."""
    home = get_astraclaw_home()
    home.mkdir(parents=True, exist_ok=True)
    for subdir in ("sessions", "memory", "skills", "logs"):
        (home / subdir).mkdir(exist_ok=True)
    ensure_default_soul_md()
    return home


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Override wins on conflicts."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def get_config_path() -> Path:
    return get_astraclaw_home() / "config.yaml"


def load_config() -> Dict[str, Any]:
    """Load config from ~/.astraclaw/config.yaml, merged with defaults.

    If the file doesn't exist, returns defaults as-is.
    """
    ensure_astraclaw_home()
    config = copy.deepcopy(DEFAULT_CONFIG)
    config_path = get_config_path()

    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                user_config = yaml.safe_load(f) or {}
            config = _deep_merge(config, user_config)
        except Exception as e:
            print(f"Warning: Failed to load config: {e}")

    return config


def load_user_config() -> Dict[str, Any]:
    """Read the raw user-level overrides from config.yaml (no defaults merged).

    Returns an empty dict when the file is missing or malformed. The wizard
    uses this to update overrides without inflating the file with full
    defaults.
    """
    ensure_astraclaw_home()
    config_path = get_config_path()
    if not config_path.exists():
        return {}
    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Warning: Failed to load user config: {e}")
        return {}
    return data if isinstance(data, dict) else {}


def save_user_config(partial: Dict[str, Any]) -> Path:
    """Merge ``partial`` into the existing user config and write it atomically.

    Only writes the keys the user has changed - defaults are not flattened
    into the file, so future default updates still propagate.
    """
    ensure_astraclaw_home()
    existing = load_user_config()
    merged = _deep_merge(existing, partial)
    config_path = get_config_path()

    config_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".config.", suffix=".yaml.tmp", dir=str(config_path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(merged, f, sort_keys=False, allow_unicode=True)
        os.replace(tmp_path, config_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return config_path
