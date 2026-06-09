"""Delegate tool - spawn one focused child agent for a self-contained subtask.

The child is a fresh AstraAgent with no parent history, no SOUL.md, and no
memory snapshot. It only knows what the parent passes via `goal` + `context`,
runs its own tool loop (capped turns), and its final message is returned to
the parent as a summary. Intermediate tool output never enters the parent's
context window - that isolation is the entire point.

Same special-case pattern as memory/todo/clarify: the registry handler runs
without a parent config (returns an unavailable-error JSON), and
agent/tool_runner.py injects the parent's config + session id + events.

v1 limits: one child at a time, blocking, depth 1 (children cannot see the
delegate tool at all - "delegation" is a blocked toolset).
"""

from __future__ import annotations

import copy
import json
import logging
import os
import platform
import time
from typing import Any, Callable, Dict, List, Optional

from ..agent.events import AgentEvents
from ..session import create_session, rewrite_session
from .registry import registry

logger = logging.getLogger(__name__)

# Toolsets a child must never have. delegation = no recursion (depth 1);
# clarify = children can't talk to the user; memory = no writes to shared
# MEMORY.md; planning = the todo plan belongs to the parent's session;
# session_search = children stay focused on the briefing, not past chats.
BLOCKED_TOOLSETS = frozenset({"delegation", "clarify", "memory", "planning", "session_search"})

DEFAULT_CHILD_MAX_TURNS = 15
CHILD_MAX_TURNS_CAP = 30
MAX_TURNS_SENTINEL = "Max turns reached. Agent stopped."


def _build_child_system_prompt(goal: str, context: Optional[str] = None) -> str:
    """Focused system prompt for a child agent (replaces SOUL.md + memory)."""
    os_name = platform.system()
    if os_name == "Windows":
        shell_hint = (
            "Shell runs via Windows shell=True semantics (cmd-compatible). "
            "Use dir, type, where, findstr -- NOT ls, cat, grep."
        )
    else:
        shell_hint = "Shell is Unix. Use ls, cat, find, grep."

    parts = [
        "You are a focused sub-agent working on one delegated task. "
        "You have no memory of any prior conversation - the briefing below "
        "is everything you know.",
        "Do not describe what you would do -- actually do it by calling the "
        "appropriate tool. Never claim to have read a file or run a command "
        "unless you actually called the tool and received its result. If you "
        "need a file's contents, call read_file; if you need to run something, "
        "call shell. Guessing instead of using a tool is a failure.",
        f"YOUR TASK:\n{goal}",
    ]
    if context and context.strip():
        parts.append(f"CONTEXT FROM THE PARENT AGENT:\n{context.strip()}")
    parts.append(f"Environment: {os_name}, working directory: {os.getcwd()}")
    parts.append(shell_hint)
    parts.append(
        "When the task is genuinely done, reply with a clear, concise report "
        "of what you actually did, what you found, any files you created or "
        "changed, and any problems you hit. Your final message is returned to "
        "the parent agent as the result, so make it self-contained."
    )
    return "\n\n".join(parts)


def _build_child_config(parent_config: Dict[str, Any], max_turns: Optional[int]) -> Dict[str, Any]:
    """Derive the child's config: same model route, no memory, capped turns,
    blocked toolsets stripped."""
    child_config = copy.deepcopy(parent_config)

    child_config.setdefault("memory", {})
    child_config["memory"]["enabled"] = False
    child_config["memory"]["user_profile_enabled"] = False

    delegation_config = parent_config.get("delegation", {})
    turns = max_turns or delegation_config.get("max_turns", DEFAULT_CHILD_MAX_TURNS)
    turns = max(1, min(int(turns), CHILD_MAX_TURNS_CAP))
    child_config.setdefault("agent", {})
    child_config["agent"]["max_turns"] = turns

    # Child toolsets = parent's enabled set (None means "all registered")
    # minus blocked ones. The child never sees the delegate schema, so
    # recursion is impossible by construction.
    parent_toolsets = parent_config.get("tools", {}).get("enabled_toolsets")
    base = set(parent_toolsets) if parent_toolsets is not None else registry.list_toolsets()
    child_config.setdefault("tools", {})
    child_config["tools"]["enabled_toolsets"] = sorted(base - BLOCKED_TOOLSETS)

    return child_config


def _forward_events(events: Optional[AgentEvents]) -> Optional[AgentEvents]:
    """Relay child tool activity to the parent's UI, but never the spinner
    (on_thinking only tracks user-facing turns)."""
    if events is None or (events.on_tool_start is None and events.on_tool_complete is None):
        return None
    return AgentEvents(
        on_thinking=None,
        on_tool_start=events.on_tool_start,
        on_tool_complete=events.on_tool_complete,
    )


def _detect_exit(final_text: str, new_messages: List[Dict[str, Any]]) -> tuple[str, str]:
    """Return (exit_reason, summary). On a max-turns exit the loop's sentinel
    text is useless, so fall back to the child's last substantive reply."""
    if final_text != MAX_TURNS_SENTINEL:
        return "completed", final_text

    for message in reversed(new_messages):
        content = message.get("content")
        if message.get("role") == "assistant" and isinstance(content, str) and content.strip():
            return "max_turns", content.strip()
    return "max_turns", ""


def _save_child_session(
    goal: str,
    new_messages: List[Dict[str, Any]],
    parent_session_id: Optional[str],
) -> Optional[str]:
    """Persist the child run as its own JSONL session (debugging aid).

    Failure here must not discard a successful delegation result, so this is
    the one place we swallow: log and return None.
    """
    try:
        child_session_id = create_session()
        rewrite_session(
            child_session_id,
            new_messages,
            meta_updates={
                "parent_id": parent_session_id or "",
                "title": f"[delegate] {' '.join(goal.split())[:60]}",
            },
        )
        return child_session_id
    except Exception as exc:
        logger.warning("Failed to save child session: %s", exc)
        return None


def delegate_tool(
    goal: str,
    context: Optional[str] = None,
    max_turns: Optional[int] = None,
    *,
    parent_config: Optional[Dict[str, Any]] = None,
    parent_session_id: Optional[str] = None,
    events: Optional[AgentEvents] = None,
    agent_factory: Optional[Callable[..., Any]] = None,
) -> str:
    """Run one child agent to completion and return its report as JSON.

    `agent_factory(config=..., system_prompt_override=...)` is injectable for
    tests; production lazily imports AstraAgent (tools must not import the
    agent package at module level).
    """
    if not isinstance(goal, str) or not goal.strip():
        return json.dumps({"error": "goal is required."}, ensure_ascii=False)
    if parent_config is None:
        return json.dumps(
            {"error": "Delegate tool is not available in this execution context."},
            ensure_ascii=False,
        )

    goal = goal.strip()
    child_config = _build_child_config(parent_config, max_turns)
    child_prompt = _build_child_system_prompt(goal, context)

    if agent_factory is None:
        from ..agent.loop import AstraAgent  # lazy: avoid tools -> agent import cycle
        agent_factory = AstraAgent

    started = time.monotonic()
    try:
        child = agent_factory(config=child_config, system_prompt_override=child_prompt)
        final_text, new_messages = child.run_conversation(
            goal,
            events=_forward_events(events),
        )
    except Exception as exc:
        logger.exception("Delegated child agent failed")
        return json.dumps(
            {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "duration_seconds": round(time.monotonic() - started, 2),
            },
            ensure_ascii=False,
        )

    duration = round(time.monotonic() - started, 2)
    exit_reason, summary = _detect_exit(final_text, new_messages)
    turns = sum(1 for m in new_messages if m.get("role") == "assistant")
    child_session_id = _save_child_session(goal, new_messages, parent_session_id)

    result: Dict[str, Any] = {
        "status": "completed" if summary else "failed",
        "exit_reason": exit_reason,
        "summary": summary,
        "turns": turns,
        "duration_seconds": duration,
    }
    if child_session_id:
        result["child_session_id"] = child_session_id
    if not summary:
        result["error"] = "Child agent produced no usable output."
    return json.dumps(result, ensure_ascii=False)


DELEGATE_SCHEMA = {
    "name": "delegate",
    "description": (
        "Spawn one focused sub-agent to handle a self-contained subtask in an "
        "isolated context. The sub-agent runs its own tool loop and only its "
        "final report comes back - its intermediate tool output never enters "
        "your context window.\n\n"
        "WHEN TO USE:\n"
        "- Context-heavy research: reading many files, large searches, web "
        "research whose raw output would flood your context\n"
        "- A self-contained chunk of work you can fully specify up front\n\n"
        "WHEN NOT TO USE:\n"
        "- A few quick tool calls -> just call the tools directly\n"
        "- Tasks needing user input -> sub-agents cannot use clarify\n"
        "- Anything requiring your conversation history -> the sub-agent "
        "starts blank\n\n"
        "IMPORTANT: the sub-agent knows NOTHING about this conversation. Put "
        "every needed fact (file paths, error messages, constraints, "
        "definitions of done) into goal/context."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal": {
                "type": "string",
                "description": (
                    "What the sub-agent should accomplish. Specific and "
                    "self-contained, with a clear definition of done."
                ),
            },
            "context": {
                "type": "string",
                "description": (
                    "Background the sub-agent needs: file paths, error "
                    "messages, constraints, prior findings. More specific = "
                    "better results."
                ),
            },
            "max_turns": {
                "type": "integer",
                "description": (
                    f"Max tool-loop turns for the sub-agent (default "
                    f"{DEFAULT_CHILD_MAX_TURNS}, cap {CHILD_MAX_TURNS_CAP}). "
                    "Lower it for simple tasks."
                ),
            },
        },
        "required": ["goal"],
    },
}


def _check_delegate_available() -> bool:
    return True


registry.register(
    name="delegate",
    toolset="delegation",
    schema=DELEGATE_SCHEMA,
    handler=lambda args: delegate_tool(
        goal=args.get("goal", ""),
        context=args.get("context"),
        max_turns=args.get("max_turns"),
        parent_config=None,
    ),
    check_fn=_check_delegate_available,
)
