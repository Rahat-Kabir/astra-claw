"""Astra-Claw agent loop - the brain.

Core conversation loop: call LLM -> check for tool calls -> dispatch -> repeat.
"""

import json
import sys
from typing import Any, Callable, Dict, List, Optional

from ..config import load_config
from ..llm import build_route, create_client, is_failover_worthy_error
from ..memory import MemoryStore
from .prompt_builder import build_system_prompt
from ..tools.registry import registry
from .context_compactor import CompactionConfig, CompactionOutcome, ContextCompactor

# Import tool modules so they register themselves
from ..tools import file_tools  # noqa: F401
from ..tools import memory_tool as memory_tool_module  # noqa: F401
from ..tools import patch_tool  # noqa: F401
from ..tools import search_tool  # noqa: F401
from ..tools import shell_tool  # noqa: F401


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

        # Memory: load frozen snapshot once at agent init.
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

        self.primary_route = build_route(model_config, fallback=False)
        self.fallback_route = build_route(model_config, fallback=True)
        if self.fallback_route == self.primary_route:
            self.fallback_route = None

        self._clients: Dict[str, Any] = {}
        self._get_client(self.primary_route["provider"])

        # Collect tool schemas from registry
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

    def _call_stream(
        self,
        route: Dict[str, str],
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        client = self._get_client(route["provider"])
        kwargs = {
            "model": route["model"],
            "messages": messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
        return client.chat.completions.create(
            **kwargs,
        )

    def _collect_stream_response(
        self,
        messages: List[Dict[str, Any]],
        stream_writer: Optional[Callable[[str], None]] = None,
        routes: Optional[List[Dict[str, str]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[str, Optional[List[Dict[str, Any]]]]:
        active_routes = list(routes) if routes is not None else [self.primary_route]
        if routes is None and self.fallback_route is not None:
            active_routes.append(self.fallback_route)

        last_error = None
        for route_index, route in enumerate(active_routes):
            content_parts = []
            tool_calls_acc = {}
            has_meaningful_output = False

            try:
                stream = self._call_stream(route, messages, tools=tools)
                for chunk in stream:
                    if not chunk.choices:
                        continue

                    delta = chunk.choices[0].delta

                    if delta.content:
                        has_meaningful_output = True
                        content_parts.append(delta.content)
                        if not tool_calls_acc:
                            if stream_writer is not None:
                                stream_writer(delta.content)
                            else:
                                sys.stdout.write(delta.content)
                                sys.stdout.flush()

                    if delta.tool_calls:
                        has_meaningful_output = True
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index if tc_delta.index is not None else 0
                            if idx not in tool_calls_acc:
                                tool_calls_acc[idx] = {
                                    "id": tc_delta.id or "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                }
                            entry = tool_calls_acc[idx]
                            if tc_delta.id:
                                entry["id"] = tc_delta.id
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    entry["function"]["name"] += tc_delta.function.name
                                if tc_delta.function.arguments:
                                    entry["function"]["arguments"] += tc_delta.function.arguments

                full_content = "".join(content_parts) or ""
                tool_calls_list = [tool_calls_acc[i] for i in sorted(tool_calls_acc)] if tool_calls_acc else None
                return full_content, tool_calls_list
            except Exception as exc:
                last_error = exc
                is_last_route = route_index == len(active_routes) - 1
                if has_meaningful_output or is_last_route or not is_failover_worthy_error(exc):
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
        serialized_messages = "\n\n".join(_format_message_for_compaction_summary(message) for message in messages_to_summarize)
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

        summary_text, _ = self._collect_stream_response(
            summary_messages,
            stream_writer=lambda _token: None,
            routes=routes,
            tools=None,
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
            return outcome.messages, outcome
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
    ) -> tuple:
        """Run a conversation with tool calling until completion.

        Returns (final_text, new_messages) where new_messages is the list
        of all messages generated this turn (user + assistant + tool messages).
        This allows the caller to persist them without the agent knowing about sessions.
        """
        self.last_compaction_outcome = None
        self.last_replay_history = list(conversation_history) if conversation_history else []

        history_messages = list(conversation_history) if conversation_history else []
        history_messages, compaction_outcome = self._maybe_compact_history(
            history_messages,
            pending_user_message=user_message,
        )
        if compaction_outcome is not None:
            self.last_compaction_outcome = compaction_outcome

        user_msg = {"role": "user", "content": user_message}
        history_messages.append(user_msg)

        # Track new messages generated this turn (for session persistence)
        new_messages = [user_msg]
        overflow_retried = False

        turn = 0
        while turn < self.max_turns:
            turn += 1

            request_messages = [{"role": "system", "content": self._build_system_prompt_text()}, *history_messages]
            try:
                full_content, tool_calls_list = self._collect_stream_response(
                    request_messages,
                    stream_writer=stream_writer,
                    tools=self.tools,
                )
            except Exception as exc:
                if overflow_retried or not _is_context_overflow_error(exc):
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

            # Append assistant message to history
            msg_dict = {"role": "assistant", "content": full_content}
            if tool_calls_list:
                msg_dict["tool_calls"] = tool_calls_list
            history_messages.append(msg_dict)
            new_messages.append(msg_dict)

            # No tool calls - we're done
            if not tool_calls_list:
                self.last_replay_history = list(history_messages)
                return full_content, new_messages

            # Execute each tool call
            for tc in tool_calls_list:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    fn_args = {}

                if fn_name == "memory":
                    from ..tools.memory_tool import memory_tool

                    result = memory_tool(
                        action=fn_args.get("action", ""),
                        target=fn_args.get("target", "memory"),
                        content=fn_args.get("content"),
                        old_text=fn_args.get("old_text"),
                        store=self.memory_store,
                    )
                else:
                    result = registry.dispatch(fn_name, fn_args)

                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                }
                history_messages.append(tool_msg)
                new_messages.append(tool_msg)

        self.last_replay_history = list(history_messages)
        return "Max turns reached. Agent stopped.", new_messages


def _is_context_overflow_error(exc: Exception) -> bool:
    haystack = f"{exc.__class__.__name__} {exc}".lower()
    markers = (
        "context length",
        "maximum context length",
        "too many tokens",
        "prompt is too long",
        "context window",
    )
    return any(marker in haystack for marker in markers)


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
