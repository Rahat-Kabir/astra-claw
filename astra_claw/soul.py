"""Global SOUL.md identity loading for Astra-Claw.

SOUL.md lives under ASTRACLAW_HOME and acts as the primary identity layer
for the agent. If missing, a starter file is seeded on first run.
"""

from pathlib import Path
import re
from typing import Optional

from .constants import get_astraclaw_home


DEFAULT_SOUL_MD = """You are Astra-Claw, an AI agent that can take actions using tools.

You are direct, practical, and concise.
You prefer doing the work over describing what you might do.
You avoid unnecessary verbosity, overengineering, and theatrical phrasing.
You explain failures clearly and keep momentum on the user's actual goal.
"""

SOUL_MAX_CHARS = 12000
_TRUNCATE_HEAD_RATIO = 0.7
_TRUNCATE_TAIL_RATIO = 0.2

_SOUL_THREAT_PATTERNS = [
    (r"ignore\s+(previous|all|above|prior)\s+instructions", "prompt_injection"),
    (r"you\s+are\s+now\s+", "role_hijack"),
    (r"do\s+not\s+tell\s+the\s+user", "deception_hide"),
    (r"system\s+prompt\s+override", "sys_prompt_override"),
    (r"disregard\s+(your|all|any)\s+(instructions|rules|guidelines)", "disregard_rules"),
]

_SOUL_INVISIBLE_CHARS = {
    "\u200b", "\u200c", "\u200d", "\u2060", "\ufeff",
    "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
}


def _soul_path() -> Path:
    return get_astraclaw_home() / "SOUL.md"


def _scan_soul_content(content: str) -> str:
    """Return safe content or a blocked marker string."""
    findings = []

    for char in _SOUL_INVISIBLE_CHARS:
        if char in content:
            findings.append(f"invisible unicode U+{ord(char):04X}")

    for pattern, pid in _SOUL_THREAT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            findings.append(pid)

    if findings:
        joined = ", ".join(findings)
        return f"[BLOCKED: SOUL.md contained potential prompt injection ({joined}). Content not loaded.]"

    return content


def _truncate_soul_content(content: str, max_chars: int = SOUL_MAX_CHARS) -> str:
    """Truncate oversized SOUL.md with a head/tail split."""
    if len(content) <= max_chars:
        return content

    head_chars = int(max_chars * _TRUNCATE_HEAD_RATIO)
    tail_chars = int(max_chars * _TRUNCATE_TAIL_RATIO)
    head = content[:head_chars]
    tail = content[-tail_chars:]
    marker = (
        f"\n\n[...truncated SOUL.md: kept {head_chars}+{tail_chars} "
        f"of {len(content)} chars.]\n\n"
    )
    return head + marker + tail


def ensure_default_soul_md() -> None:
    """Seed a starter SOUL.md on first run without overwriting user content."""
    soul_path = _soul_path()
    if soul_path.exists():
        return
    soul_path.write_text(DEFAULT_SOUL_MD, encoding="utf-8")


def load_soul_md() -> Optional[str]:
    """Load SOUL.md from ASTRACLAW_HOME, or None when unavailable."""
    soul_path = _soul_path()
    if not soul_path.exists():
        return None

    try:
        content = soul_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    if not content:
        return None

    content = _scan_soul_content(content)
    return _truncate_soul_content(content)
