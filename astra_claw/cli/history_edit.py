"""Pure helpers for rewinding session history (/retry, /undo)."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple


def find_last_user_message(
    history: List[Dict],
) -> Tuple[Optional[int], Optional[str]]:
    """Return (index, content) of the last user message, or (None, None)."""
    for i in range(len(history) - 1, -1, -1):
        if history[i].get("role") == "user":
            content = history[i].get("content", "")
            if isinstance(content, str) and content.strip():
                return i, content
    return None, None


def truncate_for_retry(history: List[Dict]) -> Tuple[List[Dict], Optional[str]]:
    """Drop the last user turn and return (truncated_history, user_text_to_resend)."""
    idx, user_text = find_last_user_message(history)
    if idx is None:
        return list(history), None
    return list(history[:idx]), user_text
