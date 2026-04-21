"""Session search tool - browse recent sessions or search past JSONL transcripts."""

from __future__ import annotations

import json

from ..session import list_recent_sessions, search_sessions
from .registry import registry


def session_search_tool(
    query: str | None = None,
    role_filter: str | None = None,
    limit: int = 3,
    exclude_session_id: str | None = None,
) -> str:
    """Browse recent sessions or search past sessions. Returns JSON string."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 3

    if query is None or not str(query).strip():
        result = list_recent_sessions(limit=limit, exclude_session_id=exclude_session_id)
    else:
        result = search_sessions(
            str(query),
            limit=limit,
            role_filter=role_filter,
            exclude_session_id=exclude_session_id,
        )
    return json.dumps(result, ensure_ascii=False)


def _check_session_search_available() -> bool:
    return True


SESSION_SEARCH_SCHEMA = {
    "name": "session_search",
    "description": (
        "Browse recent sessions or search past sessions by topic. "
        "Use this when the user refers to earlier work outside the current "
        "conversation: 'what were we doing before', 'remember when', "
        "'how did we fix X', or 'find the session about Y'. "
        "Call with no query to list recent sessions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Topic or phrase to search for. Omit to browse recent sessions.",
            },
            "role_filter": {
                "type": "string",
                "description": "Optional comma-separated roles to search: user, assistant, tool.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of sessions to return (default 3, max 5).",
                "default": 3,
            },
        },
        "required": [],
    },
}


registry.register(
    name="session_search",
    toolset="session_search",
    schema=SESSION_SEARCH_SCHEMA,
    handler=lambda args: session_search_tool(
        query=args.get("query"),
        role_filter=args.get("role_filter"),
        limit=args.get("limit", 3),
        exclude_session_id=None,
    ),
    check_fn=_check_session_search_available,
)
