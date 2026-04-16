"""Tests for the AgentEvents wiring through run_conversation."""

import types
from unittest.mock import patch

from astra_claw.agent.events import AgentEvents
from astra_claw.agent.loop import AstraAgent


class FakeFunction:
    def __init__(self, name="", arguments=""):
        self.name = name
        self.arguments = arguments


class FakeToolCallDelta:
    def __init__(self, index=0, call_id=None, function=None):
        self.index = index
        self.id = call_id
        self.function = function


class FakeDelta:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class FakeChunk:
    def __init__(self, delta):
        self.choices = [types.SimpleNamespace(delta=delta)]


class FakeCompletions:
    def __init__(self, streams):
        self._streams = list(streams)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._streams.pop(0)


class FakeClient:
    def __init__(self, streams):
        self.chat = types.SimpleNamespace(completions=FakeCompletions(streams))


def _tool_call_stream(call_id, name, arguments):
    return [
        FakeChunk(
            FakeDelta(
                tool_calls=[
                    FakeToolCallDelta(
                        index=0,
                        call_id=call_id,
                        function=FakeFunction(name=name, arguments=arguments),
                    )
                ]
            )
        )
    ]


class TestAgentEventsFiring:
    def test_on_thinking_toggles_around_each_llm_stream(self):
        """on_thinking should fire True before a stream and False once content arrives."""
        streams = [[FakeChunk(FakeDelta(content="hi"))]]
        thinking_events = []
        events = AgentEvents(on_thinking=lambda active: thinking_events.append(active))

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with patch("astra_claw.agent.loop.create_client", return_value=FakeClient(streams)):
                agent = AstraAgent()
                agent.run_conversation("hi", stream_writer=lambda _: None, events=events)

        assert thinking_events == [True, False]

    def test_tool_start_and_complete_fire_in_order_with_call_id(self):
        """on_tool_start/on_tool_complete must bracket dispatch for every call."""
        streams = [
            _tool_call_stream("call_abc", "read_file", '{"path": "README.md"}'),
            [FakeChunk(FakeDelta(content="done"))],
        ]
        starts = []
        completes = []
        thinking_events = []

        events = AgentEvents(
            on_thinking=lambda active: thinking_events.append(active),
            on_tool_start=lambda call_id, name, args: starts.append((call_id, name, args)),
            on_tool_complete=lambda call_id, name, args, result: completes.append((call_id, name, result)),
        )

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with patch("astra_claw.agent.loop.create_client", return_value=FakeClient(streams)):
                with patch(
                    "astra_claw.agent.loop.registry.dispatch",
                    return_value='{"path": "README.md", "content": "x"}',
                ):
                    agent = AstraAgent()
                    agent.run_conversation(
                        "read it",
                        stream_writer=lambda _: None,
                        events=events,
                    )

        assert starts == [("call_abc", "read_file", {"path": "README.md"})]
        assert completes == [("call_abc", "read_file", '{"path": "README.md", "content": "x"}')]
        # Two LLM calls (tool-call turn + final-text turn) => two True/False pairs.
        assert thinking_events.count(True) == 2
        assert thinking_events.count(False) == 2

    def test_no_events_is_a_no_op(self):
        """Agent must work identically when events is None (back-compat)."""
        streams = [
            _tool_call_stream("call_x", "read_file", '{"path": "x.md"}'),
            [FakeChunk(FakeDelta(content="ok"))],
        ]

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with patch("astra_claw.agent.loop.create_client", return_value=FakeClient(streams)):
                with patch(
                    "astra_claw.agent.loop.registry.dispatch",
                    return_value='{"path": "x.md", "content": "y"}',
                ):
                    agent = AstraAgent()
                    text, messages = agent.run_conversation(
                        "go", stream_writer=lambda _: None
                    )

        assert text == "ok"
        assert messages[-1] == {"role": "assistant", "content": "ok"}

    def test_compaction_summary_stream_does_not_fire_on_thinking(self):
        """Compaction summaries must not spam the user's spinner."""
        summary_stream = [FakeChunk(FakeDelta(content="- keep working"))]
        final_text_stream = [FakeChunk(FakeDelta(content="compacted reply"))]
        client = FakeClient([summary_stream, final_text_stream])

        history = [
            {"role": "user", "content": "keep"},
            {"role": "assistant", "content": "keep reply"},
            {"role": "user", "content": "middle " * 80},
            {"role": "assistant", "content": "middle reply " * 80},
            {"role": "user", "content": "recent"},
            {"role": "assistant", "content": "recent reply"},
        ]
        config = {
            "model": {"default": "gpt-5.4-mini", "provider": "openai", "context_window": 200},
            "agent": {"max_turns": 2},
            "compression": {
                "enabled": True,
                "threshold_ratio": 0.50,
                "reserve_tokens": 10,
                "keep_first_n": 2,
                "keep_last_n": 2,
                "max_passes": 1,
            },
            "memory": {"enabled": False, "user_profile_enabled": False},
        }

        thinking_events = []
        events = AgentEvents(on_thinking=lambda active: thinking_events.append(active))

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with patch("astra_claw.agent.loop.create_client", return_value=client):
                agent = AstraAgent(config=config)
                agent.run_conversation(
                    "new question",
                    conversation_history=history,
                    stream_writer=lambda _: None,
                    events=events,
                )

        # Only the final user-facing stream should toggle thinking (one True/False pair).
        assert thinking_events == [True, False]
