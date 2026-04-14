"""Astra-Claw agent loop - the brain.

Core conversation loop: call LLM -> check for tool calls -> dispatch -> repeat.
"""

import json
import sys
from typing import Any, Dict, List, Optional

from ..config import load_config
from ..llm import build_route, create_client, is_failover_worthy_error
from ..memory import MemoryStore
from .prompt_builder import build_system_prompt
from ..tools.registry import registry

# Import tool modules so they register themselves
from ..tools import file_tools  # noqa: F401
from ..tools import memory_tool as memory_tool_module  # noqa: F401
from ..tools import search_tool  # noqa: F401
from ..tools import shell_tool  # noqa: F401


class AstraAgent:
    """AI Agent with tool calling capabilities."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_config()
        model_config = self.config.get("model", {})
        tool_config = self.config.get("tools", {})

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

    def _get_client(self, provider: str) -> Any:
        if provider not in self._clients:
            self._clients[provider] = create_client(provider)
        return self._clients[provider]

    def _call_stream(self, route: Dict[str, str], messages: List[Dict[str, Any]]) -> Any:
        client = self._get_client(route["provider"])
        return client.chat.completions.create(
            model=route["model"],
            messages=messages,
            tools=self.tools if self.tools else None,
            stream=True,
        )

    def _collect_stream_response(
        self,
        messages: List[Dict[str, Any]],
    ) -> tuple[str, Optional[List[Dict[str, Any]]]]:
        routes = [self.primary_route]
        if self.fallback_route is not None:
            routes.append(self.fallback_route)

        last_error = None
        for route_index, route in enumerate(routes):
            content_parts = []
            tool_calls_acc = {}
            has_meaningful_output = False

            try:
                stream = self._call_stream(route, messages)
                for chunk in stream:
                    if not chunk.choices:
                        continue

                    delta = chunk.choices[0].delta

                    if delta.content:
                        has_meaningful_output = True
                        content_parts.append(delta.content)
                        if not tool_calls_acc:
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
                is_last_route = route_index == len(routes) - 1
                if has_meaningful_output or is_last_route or not is_failover_worthy_error(exc):
                    raise

        if last_error is not None:
            raise last_error
        raise RuntimeError("No LLM route available.")

    def run_conversation(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple:
        """Run a conversation with tool calling until completion.

        Returns (final_text, new_messages) where new_messages is the list
        of all messages generated this turn (user + assistant + tool messages).
        This allows the caller to persist them without the agent knowing about sessions.
        """
        messages = list(conversation_history) if conversation_history else []
        messages.insert(
            0,
            {
                "role": "system",
                "content": build_system_prompt(
                    memory_store=self.memory_store,
                    include_memory_hint=self.memory_store is not None,
                ),
            },
        )

        user_msg = {"role": "user", "content": user_message}
        messages.append(user_msg)

        # Track new messages generated this turn (for session persistence)
        new_messages = [user_msg]

        turn = 0
        while turn < self.max_turns:
            turn += 1

            full_content, tool_calls_list = self._collect_stream_response(messages)

            # Append assistant message to history
            msg_dict = {"role": "assistant", "content": full_content}
            if tool_calls_list:
                msg_dict["tool_calls"] = tool_calls_list
            messages.append(msg_dict)
            new_messages.append(msg_dict)

            # No tool calls - we're done
            if not tool_calls_list:
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
                messages.append(tool_msg)
                new_messages.append(tool_msg)

        return "Max turns reached. Agent stopped.", new_messages
