"""Tests for astra_claw.tools.delegate_tool."""

import json

import pytest

import astra_claw.agent.loop  # noqa: F401 - registers all tool modules (mirrors real startup)
from astra_claw.agent.events import AgentEvents
from astra_claw.agent.tool_runner import execute_tool_calls
from astra_claw.session import load_session, load_session_meta, list_sessions
from astra_claw.tools.delegate_tool import (
    BLOCKED_TOOLSETS,
    CHILD_MAX_TURNS_CAP,
    DEFAULT_CHILD_MAX_TURNS,
    DELEGATE_SCHEMA,
    MAX_TURNS_SENTINEL,
    _build_child_config,
    _build_child_system_prompt,
    delegate_tool,
)
from astra_claw.tools.registry import registry


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))


PARENT_CONFIG = {
    "model": {"default": "test-model", "provider": "openai"},
    "agent": {"max_turns": 20},
    "memory": {"enabled": True, "user_profile_enabled": True},
    "tools": {"enabled_toolsets": None},
}


class FakeChildAgent:
    """Stands in for AstraAgent; records construction and returns a canned run."""

    last_instance = None

    def __init__(self, config=None, system_prompt_override=None):
        self.config = config
        self.system_prompt_override = system_prompt_override
        self.run_calls = []
        FakeChildAgent.last_instance = self

    def run_conversation(self, user_message, events=None, **kwargs):
        self.run_calls.append({"user_message": user_message, "events": events})
        new_messages = [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": "Report: task done."},
        ]
        return "Report: task done.", new_messages


def test_schema_shape():
    assert DELEGATE_SCHEMA["name"] == "delegate"
    assert DELEGATE_SCHEMA["parameters"]["required"] == ["goal"]


def test_empty_goal_errors():
    out = delegate_tool(goal="   ", parent_config=PARENT_CONFIG)
    assert "error" in json.loads(out)


def test_standalone_registry_dispatch_is_unavailable():
    out = registry.dispatch("delegate", {"goal": "do something"})
    parsed = json.loads(out)
    assert "not available" in parsed["error"].lower()


def test_successful_delegation_returns_summary():
    out = delegate_tool(
        goal="Summarize config loading",
        context="Files: config.py",
        parent_config=PARENT_CONFIG,
        agent_factory=FakeChildAgent,
    )
    parsed = json.loads(out)
    assert parsed["status"] == "completed"
    assert parsed["exit_reason"] == "completed"
    assert parsed["summary"] == "Report: task done."
    assert parsed["turns"] == 1
    assert "duration_seconds" in parsed


def test_child_prompt_contains_goal_and_context():
    delegate_tool(
        goal="Find the bug",
        context="Error: KeyError in session.py",
        parent_config=PARENT_CONFIG,
        agent_factory=FakeChildAgent,
    )
    prompt = FakeChildAgent.last_instance.system_prompt_override
    assert "Find the bug" in prompt
    assert "KeyError in session.py" in prompt
    assert "no memory of any prior conversation" in prompt
    # Regression: a weak briefing made gpt-4o-mini children hallucinate tool use
    # (claim to have read files without calling read_file). Keep the imperative.
    assert "actually do it by calling the appropriate tool" in prompt


def test_child_config_disables_memory_and_blocks_toolsets():
    child_config = _build_child_config(PARENT_CONFIG, max_turns=None)
    assert child_config["memory"]["enabled"] is False
    assert child_config["memory"]["user_profile_enabled"] is False
    assert child_config["agent"]["max_turns"] == DEFAULT_CHILD_MAX_TURNS

    enabled = set(child_config["tools"]["enabled_toolsets"])
    assert enabled.isdisjoint(BLOCKED_TOOLSETS)
    assert "delegation" not in enabled
    assert "filesystem" in enabled
    assert "terminal" in enabled


def test_child_config_respects_parent_toolset_restriction():
    parent = {**PARENT_CONFIG, "tools": {"enabled_toolsets": ["filesystem", "delegation", "memory"]}}
    child_config = _build_child_config(parent, max_turns=None)
    assert child_config["tools"]["enabled_toolsets"] == ["filesystem"]


def test_max_turns_clamped_to_cap():
    child_config = _build_child_config(PARENT_CONFIG, max_turns=999)
    assert child_config["agent"]["max_turns"] == CHILD_MAX_TURNS_CAP
    child_config = _build_child_config(PARENT_CONFIG, max_turns=-5)
    assert child_config["agent"]["max_turns"] == 1


def test_delegation_config_default_used():
    parent = {**PARENT_CONFIG, "delegation": {"max_turns": 7}}
    child_config = _build_child_config(parent, max_turns=None)
    assert child_config["agent"]["max_turns"] == 7


def test_parent_config_not_mutated():
    before = json.dumps(PARENT_CONFIG, sort_keys=True)
    _build_child_config(PARENT_CONFIG, max_turns=5)
    assert json.dumps(PARENT_CONFIG, sort_keys=True) == before


def test_max_turns_exit_uses_last_assistant_text():
    class CappedChild(FakeChildAgent):
        def run_conversation(self, user_message, events=None, **kwargs):
            new_messages = [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": "Partial findings so far.",
                 "tool_calls": [{"id": "x", "function": {"name": "read_file", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "x", "content": "{}"},
            ]
            return MAX_TURNS_SENTINEL, new_messages

    out = delegate_tool(goal="big task", parent_config=PARENT_CONFIG, agent_factory=CappedChild)
    parsed = json.loads(out)
    assert parsed["exit_reason"] == "max_turns"
    assert parsed["summary"] == "Partial findings so far."
    assert parsed["status"] == "completed"


def test_child_crash_returns_error_json():
    class CrashingChild(FakeChildAgent):
        def run_conversation(self, user_message, events=None, **kwargs):
            raise RuntimeError("boom")

    out = delegate_tool(goal="task", parent_config=PARENT_CONFIG, agent_factory=CrashingChild)
    parsed = json.loads(out)
    assert parsed["status"] == "error"
    assert "boom" in parsed["error"]


def test_child_session_saved_with_parent_id():
    out = delegate_tool(
        goal="Investigate logging",
        parent_config=PARENT_CONFIG,
        parent_session_id="2026-06-10_deadbeef",
        agent_factory=FakeChildAgent,
    )
    parsed = json.loads(out)
    child_id = parsed["child_session_id"]
    assert any(s["id"] == child_id for s in list_sessions())

    meta = load_session_meta(child_id)
    assert meta["parent_id"] == "2026-06-10_deadbeef"
    assert meta["title"].startswith("[delegate] Investigate logging")

    messages = load_session(child_id)
    assert messages[0] == {"role": "user", "content": "Investigate logging"}
    assert messages[-1]["role"] == "assistant"


def test_events_forwarded_without_on_thinking():
    fired = []
    parent_events = AgentEvents(
        on_thinking=lambda active: fired.append(("thinking", active)),
        on_tool_start=lambda cid, name, args: fired.append(("start", name)),
        on_tool_complete=lambda cid, name, args, result: fired.append(("complete", name)),
    )
    delegate_tool(
        goal="task",
        parent_config=PARENT_CONFIG,
        events=parent_events,
        agent_factory=FakeChildAgent,
    )
    child_events = FakeChildAgent.last_instance.run_calls[0]["events"]
    assert child_events.on_thinking is None
    assert child_events.on_tool_start is parent_events.on_tool_start
    assert child_events.on_tool_complete is parent_events.on_tool_complete


def test_tool_runner_special_cases_delegate(monkeypatch):
    import astra_claw.agent.tool_runner as tool_runner

    captured = {}

    def fake_delegate_tool(goal, context=None, max_turns=None, *, parent_config=None,
                           parent_session_id=None, events=None, agent_factory=None):
        captured.update(
            goal=goal, context=context, parent_config=parent_config,
            parent_session_id=parent_session_id,
        )
        return json.dumps({"status": "completed", "summary": "ok"})

    monkeypatch.setattr(tool_runner, "delegate_tool", fake_delegate_tool)

    calls = [{
        "id": "call_1",
        "function": {"name": "delegate", "arguments": json.dumps({"goal": "g", "context": "c"})},
    }]
    messages = execute_tool_calls(
        calls,
        memory_store=None,
        parent_config=PARENT_CONFIG,
        current_session_id="parent-123",
    )
    assert captured["goal"] == "g"
    assert captured["context"] == "c"
    assert captured["parent_config"] is PARENT_CONFIG
    assert captured["parent_session_id"] == "parent-123"
    assert json.loads(messages[0]["content"])["status"] == "completed"


def test_build_child_system_prompt_without_context():
    prompt = _build_child_system_prompt("Do the thing")
    assert "YOUR TASK:\nDo the thing" in prompt
    assert "CONTEXT FROM THE PARENT AGENT" not in prompt
