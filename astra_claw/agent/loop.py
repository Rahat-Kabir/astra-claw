"""Astra-Claw agent loop — the brain.

Core conversation loop: call LLM → check for tool calls → dispatch → repeat.
"""

import json
import os
from typing import Any, Dict, List, Optional

from openai import OpenAI

from ..config import load_config
from ..constants import get_astraclaw_home
from .prompt_builder import build_system_prompt
from ..tools.registry import registry

# Import tool modules so they register themselves
from ..tools import file_tools  # noqa: F401
from ..tools import shell_tool  # noqa: F401


PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


class AstraAgent:
    """AI Agent with tool calling capabilities."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_config()
        model_config = self.config.get("model", {})

        self.model = model_config.get("default", "gpt-4o-mini")
        self.max_turns = self.config.get("agent", {}).get("max_turns", 20)

        # Create LLM client
        provider = model_config.get("provider", "openai")
        base_url = PROVIDER_BASE_URLS.get(provider, PROVIDER_BASE_URLS["openai"])
        api_key = os.getenv(PROVIDER_KEY_ENV.get(provider, "OPENAI_API_KEY"), "")

        if not api_key:
            raise RuntimeError(
                f"No API key found. Set {PROVIDER_KEY_ENV.get(provider)} environment variable."
            )

        self.client = OpenAI(base_url=base_url, api_key=api_key)

        # Collect tool schemas from registry
        self.tools = registry.get_definitions()

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
        messages.insert(0, {"role": "system", "content": build_system_prompt()})

        user_msg = {"role": "user", "content": user_message}
        messages.append(user_msg)

        # Track new messages generated this turn (for session persistence)
        new_messages = [user_msg]

        turn = 0
        while turn < self.max_turns:
            turn += 1

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.tools if self.tools else None,
            )

            choice = response.choices[0]
            assistant_msg = choice.message

            # Append assistant message to history
            msg_dict = {"role": "assistant", "content": assistant_msg.content or ""}
            if assistant_msg.tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in assistant_msg.tool_calls
                ]
            messages.append(msg_dict)
            new_messages.append(msg_dict)

            # No tool calls — we're done
            if not assistant_msg.tool_calls:
                return assistant_msg.content or "", new_messages

            # Execute each tool call
            for tc in assistant_msg.tool_calls:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    fn_args = {}

                result = registry.dispatch(fn_name, fn_args)

                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                }
                messages.append(tool_msg)
                new_messages.append(tool_msg)

        return "Max turns reached. Agent stopped.", new_messages
