"""Tool dispatch round — executes one batch of tool calls with event hooks.

Extracted from agent.loop so the loop stays focused on LLM orchestration.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from ..memory import MemoryStore
from ..tools.clarify_tool import clarify_tool
from ..tools.memory_tool import memory_tool
from ..tools.registry import registry
from ..tools.todo_tool import TodoStore, todo_tool
from .events import AgentEvents


def execute_tool_calls(
    tool_calls: List[Dict[str, Any]],
    *,
    memory_store: Optional[MemoryStore],
    todo_store: Optional[TodoStore] = None,
    clarify_callback: Optional[Callable[[str, Optional[List[str]]], str]] = None,
    events: Optional[AgentEvents] = None,
) -> List[Dict[str, Any]]:
    """Dispatch each tool call and return the tool-role messages."""
    tool_messages: List[Dict[str, Any]] = []

    for tc in tool_calls:
        fn_name = tc["function"]["name"]
        try:
            fn_args = json.loads(tc["function"]["arguments"])
        except json.JSONDecodeError:
            fn_args = {}

        call_id = tc.get("id", "")

        if events is not None and events.on_tool_start is not None:
            events.on_tool_start(call_id, fn_name, fn_args)

        if fn_name == "memory":
            result = memory_tool(
                action=fn_args.get("action", ""),
                target=fn_args.get("target", "memory"),
                content=fn_args.get("content"),
                old_text=fn_args.get("old_text"),
                store=memory_store,
            )
        elif fn_name == "todo":
            result = todo_tool(
                todos=fn_args.get("todos"),
                merge=fn_args.get("merge", False),
                store=todo_store,
            )
        elif fn_name == "clarify":
            result = clarify_tool(
                question=fn_args.get("question", ""),
                choices=fn_args.get("choices"),
                callback=clarify_callback,
            )
        else:
            result = registry.dispatch(fn_name, fn_args)

        if events is not None and events.on_tool_complete is not None:
            events.on_tool_complete(call_id, fn_name, fn_args, result)

        tool_messages.append({
            "role": "tool",
            "tool_call_id": call_id,
            "content": result,
        })

    return tool_messages
