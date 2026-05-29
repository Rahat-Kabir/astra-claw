"""Auto-generate short session titles from the first substantive exchange.

Runs on a daemon thread after a user-facing turn so it never adds latency to
the reply. Greeting-only openers are skipped until a substantive user message
lands. Failures are silent - titles are a nice-to-have.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Optional

from ..llm import complete_once
from ..session import get_session_title, set_session_title

logger = logging.getLogger(__name__)

_TITLE_PROMPT = (
    "Generate a short, descriptive title (3-5 words) for a conversation "
    "that starts with the following exchange. The title should capture "
    "the main topic or intent. Return ONLY the title text, nothing else. "
    "No quotes, no trailing punctuation, no prefixes like 'Title:'."
)

_GREETING_PHRASES = frozenset(
    {
        "hey",
        "hi",
        "hello",
        "yo",
        "sup",
        "hiya",
        "howdy",
        "thanks",
        "thank you",
        "thx",
        "ty",
        "ok",
        "okay",
        "k",
        "bye",
        "goodbye",
        "cya",
        "yes",
        "no",
        "yep",
        "nope",
        "yeah",
        "nah",
        "how are you",
        "whats up",
        "what's up",
        "good morning",
        "good evening",
        "good night",
    }
)

_GREETING_STARTERS = frozenset({"hey", "hi", "hello", "yo", "sup", "thanks", "thank"})


def is_low_signal_user_message(message: str) -> bool:
    """Return True for greetings and other messages too weak to title from."""
    text = (message or "").strip()
    if not text:
        return True

    normalized = re.sub(r"[^\w\s']", " ", text.lower())
    normalized = " ".join(normalized.split())
    if not normalized:
        return True
    if len(normalized) <= 3:
        return True
    if normalized in _GREETING_PHRASES:
        return True

    words = normalized.split()
    if len(words) <= 3 and words[0] in _GREETING_STARTERS:
        return True
    if len(words) == 2 and words[0] == "thank" and words[1] == "you":
        return True
    return False


def generate_title(
    user_message: str,
    assistant_response: str,
    *,
    provider: str,
    model: str,
    timeout: float = 30.0,
    api_key: Optional[str] = None,
) -> Optional[str]:
    """Generate a title from the first exchange. Returns None on failure."""
    user_snippet = (user_message or "")[:500]
    assistant_snippet = (assistant_response or "")[:500]

    messages = [
        {"role": "system", "content": _TITLE_PROMPT},
        {
            "role": "user",
            "content": f"User: {user_snippet}\n\nAssistant: {assistant_snippet}",
        },
    ]

    try:
        raw = complete_once(
            messages=messages,
            provider=provider,
            model=model,
            max_tokens=30,
            temperature=0.3,
            timeout=timeout,
            api_key=api_key,
        )
    except Exception as e:
        logger.debug("title generation failed: %s", e)
        return None

    title = (raw or "").strip().strip('"\'')
    if title.lower().startswith("title:"):
        title = title[6:].strip()
    title = title.rstrip(".!?,;:")
    if len(title) > 80:
        title = title[:77] + "..."
    return title or None


def auto_title_session(
    session_id: str,
    user_message: str,
    assistant_response: str,
    *,
    provider: str,
    model: str,
    api_key: Optional[str] = None,
) -> None:
    """Generate a title and persist it if one isn't already set."""
    if not session_id:
        return

    try:
        if get_session_title(session_id):
            return
    except Exception:
        return

    title = generate_title(
        user_message,
        assistant_response,
        provider=provider,
        model=model,
        api_key=api_key,
    )
    if not title:
        return

    try:
        set_session_title(session_id, title)
        logger.debug("auto-generated session title: %s", title)
    except Exception as e:
        logger.debug("failed to persist title: %s", e)


def maybe_auto_title(
    session_id: str,
    user_message: str,
    assistant_response: str,
    *,
    user_msg_count: int,
    provider: str,
    model: str,
    enabled: bool = True,
    api_key: Optional[str] = None,
) -> Optional[threading.Thread]:
    """Fire-and-forget title generation after the first substantive exchange.

    Returns the spawned thread (mainly for tests); None if we skipped.
    """
    del user_msg_count  # kept for REPL call-site compatibility

    if not enabled:
        return None
    if not session_id or not user_message or not assistant_response:
        return None
    if is_low_signal_user_message(user_message):
        return None

    try:
        if get_session_title(session_id):
            return None
    except Exception:
        return None

    thread = threading.Thread(
        target=auto_title_session,
        args=(session_id, user_message, assistant_response),
        kwargs={"provider": provider, "model": model, "api_key": api_key},
        daemon=True,
        name="auto-title",
    )
    thread.start()
    return thread
