"""Memory tool — thin wrapper over MemoryStore.

Schema + JSON dispatch only. All storage and policy lives in astra_claw.memory.
The agent loop special-cases this tool to inject its MemoryStore instance.
"""

import json
from typing import Optional

from ..memory import MemoryStore
from .registry import registry


MEMORY_SCHEMA = {
    "name": "memory",
    "description": (
        "Save durable information to persistent memory that survives across sessions. "
        "Memory is injected into future turns, so keep entries compact and focused on "
        "facts that will still matter later.\n\n"
        "WHEN TO SAVE (do this proactively, don't wait to be asked):\n"
        "- User corrects you or says 'remember this' / 'don't do that again'\n"
        "- User shares a preference, habit, or personal detail (name, role, coding style)\n"
        "- You discover something stable about the environment or project conventions\n"
        "- You learn an API quirk or workflow specific to this user's setup\n\n"
        "PRIORITY: User preferences and corrections > environment facts > procedural notes. "
        "The most valuable memory prevents the user from having to repeat themselves.\n\n"
        "Do NOT save task progress, session outcomes, completed-work logs, or temporary "
        "TODO state.\n\n"
        "TWO TARGETS:\n"
        "- 'user': who the user is — name, role, preferences, communication style\n"
        "- 'memory': your notes — environment facts, project conventions, tool quirks\n\n"
        "ACTIONS: add (new entry), replace (update existing via old_text), "
        "remove (delete via old_text)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "replace", "remove"],
                "description": "The action to perform.",
            },
            "target": {
                "type": "string",
                "enum": ["memory", "user"],
                "description": "Which store: 'memory' for agent notes, 'user' for user profile.",
            },
            "content": {
                "type": "string",
                "description": "Entry content. Required for 'add' and 'replace'.",
            },
            "old_text": {
                "type": "string",
                "description": "Short unique substring identifying the entry to replace or remove.",
            },
        },
        "required": ["action", "target"],
    },
}


def memory_tool(
    action: str,
    target: str = "memory",
    content: Optional[str] = None,
    old_text: Optional[str] = None,
    store: Optional[MemoryStore] = None,
) -> str:
    """Dispatch a memory action against a MemoryStore. Returns a JSON string."""
    if store is None:
        return json.dumps(
            {"success": False, "error": "Memory store unavailable. Memory may be disabled in config."},
            ensure_ascii=False,
        )

    if target not in ("memory", "user"):
        return json.dumps(
            {"success": False, "error": f"Invalid target '{target}'. Use 'memory' or 'user'."},
            ensure_ascii=False,
        )

    if action == "add":
        if not content:
            return json.dumps(
                {"success": False, "error": "content is required for 'add'."},
                ensure_ascii=False,
            )
        result = store.add(target, content)
    elif action == "replace":
        if not old_text:
            return json.dumps(
                {"success": False, "error": "old_text is required for 'replace'."},
                ensure_ascii=False,
            )
        if not content:
            return json.dumps(
                {"success": False, "error": "content is required for 'replace'."},
                ensure_ascii=False,
            )
        result = store.replace(target, old_text, content)
    elif action == "remove":
        if not old_text:
            return json.dumps(
                {"success": False, "error": "old_text is required for 'remove'."},
                ensure_ascii=False,
            )
        result = store.remove(target, old_text)
    else:
        return json.dumps(
            {"success": False, "error": f"Unknown action '{action}'. Use: add, replace, remove."},
            ensure_ascii=False,
        )

    return json.dumps(result, ensure_ascii=False)


def _check_memory_available() -> bool:
    return True


registry.register(
    name="memory",
    toolset="memory",
    schema=MEMORY_SCHEMA,
    handler=lambda args: memory_tool(
        action=args.get("action", ""),
        target=args.get("target", "memory"),
        content=args.get("content"),
        old_text=args.get("old_text"),
        store=None,
    ),
    check_fn=_check_memory_available,
)
