"""Tests for clarify_callback threading through execute_tool_calls."""

import json
from unittest.mock import patch

from astra_claw.agent.tool_runner import execute_tool_calls


def _call(name: str, args: dict, call_id: str = "call_1"):
    return {
        "id": call_id,
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def test_clarify_callback_is_injected_into_handler():
    captured = {}

    def cb(question, choices):
        captured["question"] = question
        captured["choices"] = choices
        return "prod"

    tool_calls = [_call("clarify", {"question": "Which env?", "choices": ["dev", "prod"]})]
    messages = execute_tool_calls(
        tool_calls,
        memory_store=None,
        clarify_callback=cb,
    )

    assert captured == {"question": "Which env?", "choices": ["dev", "prod"]}
    payload = json.loads(messages[0]["content"])
    assert payload["user_response"] == "prod"


def test_clarify_without_callback_returns_unavailable_error():
    tool_calls = [_call("clarify", {"question": "Which env?"})]
    messages = execute_tool_calls(tool_calls, memory_store=None)

    payload = json.loads(messages[0]["content"])
    assert "error" in payload
    assert "not available" in payload["error"].lower()


def test_clarify_other_tools_unaffected_by_callback_param():
    """Non-clarify tools must still dispatch normally when a callback is present."""
    tool_calls = [_call("not_a_real_tool", {})]
    messages = execute_tool_calls(
        tool_calls,
        memory_store=None,
        clarify_callback=lambda q, c: "irrelevant",
    )
    payload = json.loads(messages[0]["content"])
    assert "error" in payload
    assert "Unknown tool" in payload["error"]


def test_session_search_receives_current_session_id():
    tool_calls = [_call("session_search", {"query": "clarify"})]

    with patch(
        "astra_claw.agent.tool_runner.session_search_tool",
        return_value='{"success": true, "count": 0, "results": []}',
    ) as mock_session_search:
        messages = execute_tool_calls(
            tool_calls,
            memory_store=None,
            current_session_id="session-123",
        )

    mock_session_search.assert_called_once_with(
        query="clarify",
        role_filter=None,
        limit=3,
        exclude_session_id="session-123",
    )
    payload = json.loads(messages[0]["content"])
    assert payload["success"] is True
