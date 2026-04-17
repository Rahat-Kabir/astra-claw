"""Todo tool - in-memory planning list, one per agent session.

Schema + JSON dispatch only. The store lives on the AstraAgent instance
and the agent loop special-cases this tool to inject it (same pattern as
memory_tool).

Design:
- Single `todo` tool. Pass `todos` to write, omit to read.
- Every call returns the full current list + summary counts.
- merge=False replaces the list; merge=True updates by id and appends.
- On context compaction, active items are re-injected so the model
  does not lose its plan.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .registry import registry


VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled"}


class TodoStore:
    """In-memory ordered todo list. One instance per AstraAgent."""

    def __init__(self) -> None:
        self._items: List[Dict[str, str]] = []

    def write(self, todos: List[Dict[str, Any]], merge: bool = False) -> List[Dict[str, str]]:
        """Write todos. Returns the full current list after writing."""
        if not merge:
            self._items = [self._validate(t) for t in todos]
            return self.read()

        existing = {item["id"]: item for item in self._items}
        for t in todos:
            item_id = str(t.get("id", "")).strip()
            if not item_id:
                continue
            if item_id in existing:
                if "content" in t and t["content"]:
                    existing[item_id]["content"] = str(t["content"]).strip()
                if "status" in t and t["status"]:
                    status = str(t["status"]).strip().lower()
                    if status in VALID_STATUSES:
                        existing[item_id]["status"] = status
            else:
                validated = self._validate(t)
                existing[validated["id"]] = validated
                self._items.append(validated)

        seen: set = set()
        rebuilt: List[Dict[str, str]] = []
        for item in self._items:
            current = existing.get(item["id"], item)
            if current["id"] not in seen:
                rebuilt.append(current)
                seen.add(current["id"])
        self._items = rebuilt
        return self.read()

    def read(self) -> List[Dict[str, str]]:
        return [item.copy() for item in self._items]

    def has_items(self) -> bool:
        return len(self._items) > 0

    def format_for_injection(self) -> Optional[str]:
        """Render active items for post-compaction injection, or None."""
        if not self._items:
            return None

        markers = {
            "completed": "[x]",
            "in_progress": "[>]",
            "pending": "[ ]",
            "cancelled": "[~]",
        }
        active = [i for i in self._items if i["status"] in ("pending", "in_progress")]
        if not active:
            return None

        lines = ["[Your active task list was preserved across context compaction]"]
        for item in active:
            marker = markers.get(item["status"], "[?]")
            lines.append(f"- {marker} {item['id']}. {item['content']} ({item['status']})")
        return "\n".join(lines)

    @staticmethod
    def _validate(item: Dict[str, Any]) -> Dict[str, str]:
        item_id = str(item.get("id", "")).strip() or "?"
        content = str(item.get("content", "")).strip() or "(no description)"
        status = str(item.get("status", "pending")).strip().lower()
        if status not in VALID_STATUSES:
            status = "pending"
        return {"id": item_id, "content": content, "status": status}


def todo_tool(
    todos: Optional[List[Dict[str, Any]]] = None,
    merge: bool = False,
    store: Optional[TodoStore] = None,
) -> str:
    """Read or write the session todo list. Returns JSON string."""
    if store is None:
        return json.dumps(
            {"success": False, "error": "Todo store unavailable."},
            ensure_ascii=False,
        )

    if todos is not None:
        items = store.write(todos, merge)
    else:
        items = store.read()

    summary = {
        "total": len(items),
        "pending": sum(1 for i in items if i["status"] == "pending"),
        "in_progress": sum(1 for i in items if i["status"] == "in_progress"),
        "completed": sum(1 for i in items if i["status"] == "completed"),
        "cancelled": sum(1 for i in items if i["status"] == "cancelled"),
    }
    return json.dumps({"success": True, "todos": items, "summary": summary}, ensure_ascii=False)


TODO_SCHEMA = {
    "name": "todo",
    "description": (
        "Manage your task list for the current session. Use this for complex "
        "tasks with 3+ steps or when the user provides multiple tasks.\n\n"
        "Call with no parameters to read the current list.\n\n"
        "Writing:\n"
        "- Provide 'todos' array to create/update items.\n"
        "- merge=false (default): replace the entire list with a fresh plan.\n"
        "- merge=true: update existing items by id, add any new ones.\n\n"
        "Each item: {id: string, content: string, "
        "status: pending|in_progress|completed|cancelled}.\n"
        "List order is priority. Only ONE item in_progress at a time.\n"
        "Mark items completed immediately when done. If something fails, "
        "cancel it and add a revised item.\n\n"
        "Do NOT use this for durable facts (use 'memory' for that). "
        "Todos are session-scoped and discarded when the session ends."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "Task items to write. Omit to read the current list.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Unique item identifier."},
                        "content": {"type": "string", "description": "Task description."},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed", "cancelled"],
                            "description": "Current status.",
                        },
                    },
                    "required": ["id", "content", "status"],
                },
            },
            "merge": {
                "type": "boolean",
                "description": (
                    "true: update existing items by id, add new ones. "
                    "false (default): replace the entire list."
                ),
                "default": False,
            },
        },
        "required": [],
    },
}


def _check_todo_available() -> bool:
    return True


registry.register(
    name="todo",
    toolset="planning",
    schema=TODO_SCHEMA,
    handler=lambda args: todo_tool(
        todos=args.get("todos"),
        merge=args.get("merge", False),
        store=None,
    ),
    check_fn=_check_todo_available,
)
