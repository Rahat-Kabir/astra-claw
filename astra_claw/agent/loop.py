"""Astra-Claw agent loop - the brain.

Orchestrates the conversation:
- builds the system prompt
- streams LLM responses (agent.streaming)
- dispatches tool calls (agent.tool_runner)
- persists memory and triggers compaction (agent.context_compactor)
- emits optional UI events (agent.events)
"""

import json
from typing import Any, Callable, Dict, List, Optional

from ..config import load_config
from ..llm import build_route, create_client, is_failover_worthy_error
from ..memory import MemoryStore
from .context_compactor import CompactionConfig, CompactionOutcome, ContextCompactor
from .events import AgentEvents
from .prompt_builder import build_system_prompt
from .streaming import collect_stream_response, is_context_overflow_error
from .tool_runner import execute_tool_calls
from ..tools.registry import registry
from ..tools.todo_tool import TodoStore

# Import tool modules so they register themselves at agent import time.
from ..tools import clarify_tool as clarify_tool_module  # noqa: F401
from ..tools import file_tools  # noqa: F401
from ..tools import memory_tool as memory_tool_module  # noqa: F401
from ..tools import patch_tool  # noqa: F401
from ..tools import search_tool  # noqa: F401
from ..tools import session_search_tool as session_search_tool_module  # noqa: F401
from ..tools import shell_tool  # noqa: F401
from ..tools import todo_tool as todo_tool_module  # noqa: F401
from ..tools import web_tools  # noqa: F401


class AstraAgent:
    """AI Agent with tool calling capabilities."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_config()
        model_config = self.config.get("model", {})
        tool_config = self.config.get("tools", {})
        compression_config = self.config.get("compression", {})

        self.max_turns = self.config.get("agent", {}).get("max_turns", 20)
        enabled_toolsets = tool_config.get("enabled_toolsets")
        self.enabled_toolsets = set(enabled_toolsets) if enabled_toolsets is not None else None

        memory_config = self.config.get("memory", {})
        memory_enabled = memory_config.get("enabled", False)
        user_profile_enabled = memory_config.get("user_profile_enabled", False)
        if memory_enabled or user_profile_enabled:
            self.memory_store = MemoryStore(
                memory_char_limit=memory_config.get("memory_char_limit", 2200),
                user_char_limit=memory_config.get("user_char_limit", 1375),
            )
            self.memory_store.load_from_disk()
        else:
            self.memory_store = None

        self.todo_store = TodoStore()

        self.primary_route = build_route(model_config, fallback=False)
        self.fallback_route = build_route(model_config, fallback=True)
        if self.fallback_route == self.primary_route:
            self.fallback_route = None

        self._clients: Dict[str, Any] = {}
        self._get_client(self.primary_route["provider"])

        self.tools = registry.get_definitions(enabled_toolsets=self.enabled_toolsets)
        self.compactor = ContextCompactor(
            CompactionConfig(
                context_window=model_config.get("context_window", 128000),
                threshold_ratio=compression_config.get("threshold_ratio", 0.80),
                reserve_tokens=compression_config.get("reserve_tokens", 4000),
                keep_first_n=compression_config.get("keep_first_n", 2),
                keep_last_n=compression_config.get("keep_last_n", 6),
                max_passes=compression_config.get("max_passes", 2),
                summary_model=compression_config.get("summary_model"),
            ),
            tool_schemas=self.tools,
        )
        self.compression_enabled = compression_config.get("enabled", True)
        self.last_compaction_outcome: Optional[CompactionOutcome] = None
        self.last_replay_history: List[Dict[str, Any]] = []

    def _get_client(self, provider: str) -> Any:
        if provider not in self._clients:
            self._clients[provider] = create_client(provider)
        return self._clients[provider]

    def _run_one_stream(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        stream_writer: Optional[Callable[[str], None]] = None,
        on_thinking: Optional[Callable[[bool], None]] = None,
        routes: Optional[List[Dict[str, str]]] = None,
    ) -> tuple[str, Optional[List[Dict[str, Any]]]]:
        """Run one streamed completion with optional fallback between routes."""
        active_routes = list(routes) if routes is not None else [self.primary_route]
        if routes is None and self.fallback_route is not None:
            active_routes.append(self.fallback_route)

        last_error: Optional[Exception] = None
        for route_index, route in enumerate(active_routes):
            try:
                client = self._get_client(route["provider"])
                full_content, tool_calls_list, has_meaningful_output = collect_stream_response(
                    client,
                    route,
                    messages,
                    tools=tools,
                    stream_writer=stream_writer,
                    on_thinking=on_thinking,
                )
                return full_content, tool_calls_list
            except Exception as exc:
                last_error = exc
                is_last_route = route_index == len(active_routes) - 1
                if is_last_route or not is_failover_worthy_error(exc):
                    raise

        if last_error is not None:
            raise last_error
        raise RuntimeError("No LLM route available.")

    def _build_system_prompt_text(self) -> str:
        return build_system_prompt(
            memory_store=self.memory_store,
            include_memory_hint=self.memory_store is not None,
        )

    def _summarize_for_compaction(
        self,
        messages_to_summarize: List[Dict[str, Any]],
        previous_summary: Optional[str] = None,
    ) -> str:
        serialized_messages = "\n\n".join(
            _format_message_for_compaction_summary(message) for message in messages_to_summarize
        )
        prompt_parts = [
            "You are compressing prior conversation context for a coding agent.",
            "Write a concise durable summary of facts needed for future turns.",
            "Keep user goals, decisions, constraints, unresolved work, and important tool outcomes.",
            "Do not invent facts. Do not include filler. Prefer short bullet points.",
        ]
        if previous_summary:
            prompt_parts.append("Previous compacted summary:\n" + previous_summary)
        prompt_parts.append("Conversation segment to compress:\n" + (serialized_messages or "(no messages)"))
        summary_messages = [
            {"role": "system", "content": "\n\n".join(prompt_parts)},
            {"role": "user", "content": "Produce the updated compacted context summary now."},
        ]

        routes = None
        if self.compactor.config.summary_model:
            routes = [{
                "provider": self.primary_route["provider"],
                "model": self.compactor.config.summary_model,
            }]

        summary_text, _ = self._run_one_stream(
            summary_messages,
            tools=None,
            stream_writer=lambda _token: None,
            on_thinking=None,
            routes=routes,
        )
        return summary_text.strip()

    def _maybe_compact_history(
        self,
        conversation_history: Optional[List[Dict[str, Any]]],
        *,
        pending_user_message: Optional[str] = None,
        force: bool = False,
    ) -> tuple[List[Dict[str, Any]], Optional[CompactionOutcome]]:
        history = list(conversation_history) if conversation_history else []
        if not self.compression_enabled:
            return history, None

        system_prompt = self._build_system_prompt_text()
        outcome = self.compactor.compact(
            system_prompt=system_prompt,
            history=history,
            summarize_fn=self._summarize_for_compaction,
            force=force or self.compactor.should_compact(
                system_prompt=system_prompt,
                history=history,
                pending_user_message=pending_user_message,
            ),
        )
        if outcome.did_compact:
            messages = list(outcome.messages)
            todo_note = self.todo_store.format_for_injection() if self.todo_store else None
            if todo_note:
                messages.append({"role": "user", "content": todo_note})
            return messages, outcome
        return history, None

    def compact_history(
        self,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        *,
        force: bool = True,
    ) -> CompactionOutcome:
        history = list(conversation_history) if conversation_history else []
        compacted_history, outcome = self._maybe_compact_history(history, force=force)
        if outcome is None:
            outcome = CompactionOutcome(
                did_compact=False,
                messages=compacted_history,
                summary_text="",
                estimated_tokens_before=self.compactor.estimate_request_tokens(
                    system_prompt=self._build_system_prompt_text(),
                    history=history,
                ),
                estimated_tokens_after=self.compactor.estimate_request_tokens(
                    system_prompt=self._build_system_prompt_text(),
                    history=history,
                ),
                dropped_messages=0,
                passes=0,
            )
        self.last_compaction_outcome = outcome if outcome.did_compact else None
        self.last_replay_history = list(outcome.messages)
        return outcome

    def run_conversation(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        stream_writer: Optional[Callable[[str], None]] = None,
        *,
        events: Optional[AgentEvents] = None,
        clarify_callback: Optional[Callable[[str, Optional[List[str]]], str]] = None,
        current_session_id: Optional[str] = None,
    ) -> tuple:
        """Run a conversation with tool calling until completion.

        Returns (final_text, new_messages). `events` is an optional
        AgentEvents bundle for CLI/TUI feedback; all hooks are no-ops when
        absent.
        """
        self.last_compaction_outcome = None
        self.last_replay_history = list(conversation_history) if conversation_history else []

        on_thinking = events.on_thinking if events is not None else None

        history_messages = list(conversation_history) if conversation_history else []
        history_messages, compaction_outcome = self._maybe_compact_history(
            history_messages,
            pending_user_message=user_message,
        )
        if compaction_outcome is not None:
            self.last_compaction_outcome = compaction_outcome

        user_msg = {"role": "user", "content": user_message}
        history_messages.append(user_msg)

        new_messages = [user_msg]
        overflow_retried = False

        turn = 0
        while turn < self.max_turns:
            turn += 1

            request_messages = [
                {"role": "system", "content": self._build_system_prompt_text()},
                *history_messages,
            ]
            try:
                full_content, tool_calls_list = self._run_one_stream(
                    request_messages,
                    tools=self.tools,
                    stream_writer=stream_writer,
                    on_thinking=on_thinking,
                )
            except Exception as exc:
                if overflow_retried or not is_context_overflow_error(exc):
                    raise
                compacted_history, overflow_outcome = self._maybe_compact_history(
                    history_messages,
                    force=True,
                )
                if overflow_outcome is None or compacted_history == history_messages:
                    raise
                history_messages = compacted_history
                self.last_compaction_outcome = overflow_outcome
                overflow_retried = True
                continue

            msg_dict = {"role": "assistant", "content": full_content}
            if tool_calls_list:
                msg_dict["tool_calls"] = tool_calls_list
            history_messages.append(msg_dict)
            new_messages.append(msg_dict)

            if not tool_calls_list:
                self.last_replay_history = list(history_messages)
                return full_content, new_messages

            tool_messages = execute_tool_calls(
                tool_calls_list,
                memory_store=self.memory_store,
                todo_store=self.todo_store,
                clarify_callback=clarify_callback,
                current_session_id=current_session_id,
                events=events,
            )
            history_messages.extend(tool_messages)
            new_messages.extend(tool_messages)

        self.last_replay_history = list(history_messages)
        return "Max turns reached. Agent stopped.", new_messages


def _format_message_for_compaction_summary(message: Dict[str, Any], max_chars: int = 1200) -> str:
    role = message.get("role", "unknown")
    parts = [f"role={role}"]

    if role == "assistant" and message.get("tool_calls"):
        tool_names = [call.get("function", {}).get("name", "") for call in message.get("tool_calls", [])]
        parts.append("tool_calls=" + ", ".join(name for name in tool_names if name))
    if role == "tool":
        parts.append(f"tool_call_id={message.get('tool_call_id', '')}")

    content = message.get("content", "")
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    content = content.strip()
    if len(content) > max_chars:
        content = content[:max_chars] + "... [truncated]"
    parts.append("content=" + content)
    return "\n".join(parts)
