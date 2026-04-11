import types
from unittest.mock import patch

from astra_claw.agent.loop import AstraAgent


class FakeFunction:
    """Mimics the streamed function payload on a tool call delta."""

    def __init__(self, name="", arguments=""):
        self.name = name
        self.arguments = arguments


class FakeToolCallDelta:
    """Mimics one streamed tool call delta entry from the OpenAI SDK."""

    def __init__(self, index=0, call_id=None, function=None):
        self.index = index
        self.id = call_id
        self.function = function


class FakeDelta:
    """Mimics the delta object on one streamed choice chunk."""

    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class FakeChunk:
    """Mimics one streamed chunk with a single choice delta."""

    def __init__(self, delta):
        self.choices = [types.SimpleNamespace(delta=delta)]


class FakeCompletions:
    """Returns predefined streams one call at a time.

    AstraAgent calls `chat.completions.create(..., stream=True)` on every turn.
    This fake returns the next prepared stream each time `create()` is called.
    """

    def __init__(self, streams):
        self._streams = list(streams)

    def create(self, **kwargs):
        return self._streams.pop(0)


class FakeChat:
    """Holds the fake completions API surface."""

    def __init__(self, streams):
        self.completions = FakeCompletions(streams)


class FakeClient:
    """Minimal fake OpenAI client used by AstraAgent tests."""

    def __init__(self, streams):
        self.chat = FakeChat(streams)


class TestAstraAgentLoop:
    def test_run_conversation_returns_plain_text_without_tool_calls(self):
        """Agent should return streamed text directly when no tool call is emitted."""
        streams = [
            [
                FakeChunk(FakeDelta(content="Hello")),
                FakeChunk(FakeDelta(content=" world")),
            ]
        ]

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with patch("astra_claw.agent.loop.OpenAI", return_value=FakeClient(streams)):
                agent = AstraAgent()
                text, new_messages = agent.run_conversation("hi")

        assert text == "Hello world"
        assert new_messages == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "Hello world"},
        ]

    def test_run_conversation_executes_tool_call_then_returns_final_text(self):
        """Agent should dispatch a tool call, append the tool message, then continue."""
        tool_call_stream = [
            FakeChunk(
                FakeDelta(
                    tool_calls=[
                        FakeToolCallDelta(
                            index=0,
                            call_id="call_123",
                            function=FakeFunction(
                                name="read_file",
                                arguments='{"path": "README.md"}',
                            ),
                        )
                    ]
                )
            )
        ]
        final_text_stream = [
            FakeChunk(FakeDelta(content="Done reading file.")),
        ]
        streams = [tool_call_stream, final_text_stream]

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with patch("astra_claw.agent.loop.OpenAI", return_value=FakeClient(streams)):
                with patch(
                    "astra_claw.agent.loop.registry.dispatch",
                    return_value='{"path": "README.md", "content": "example"}',
                ) as mock_dispatch:
                    agent = AstraAgent()
                    text, new_messages = agent.run_conversation("read the readme")

        assert text == "Done reading file."
        mock_dispatch.assert_called_once_with("read_file", {"path": "README.md"})
        assert new_messages == [
            {"role": "user", "content": "read the readme"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path": "README.md"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_123",
                "content": '{"path": "README.md", "content": "example"}',
            },
            {"role": "assistant", "content": "Done reading file."},
        ]

 
    def test_run_conversation_uses_empty_args_when_tool_json_is_invalid(self):
        """Agent should fall back to {} when streamed tool arguments are invalid JSON."""
        tool_call_stream = [
            FakeChunk(
                FakeDelta(
                    tool_calls=[
                        FakeToolCallDelta(
                            index=0,
                            call_id="call_bad_json",
                            function=FakeFunction(
                                name="read_file",
                                arguments='{"path": "README.md"',  # missing closing brace
                            ),
                        )
                    ]
                )
            )
        ]
        final_text_stream = [
            FakeChunk(FakeDelta(content="Handled invalid args.")),
        ]
        streams = [tool_call_stream, final_text_stream]

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with patch("astra_claw.agent.loop.OpenAI", return_value=FakeClient(streams)):
                with patch(
                    "astra_claw.agent.loop.registry.dispatch",
                    return_value='{"error": "No path provided"}',
                ) as mock_dispatch:
                    agent = AstraAgent()
                    text, new_messages = agent.run_conversation("read the readme")

        assert text == "Handled invalid args."
        mock_dispatch.assert_called_once_with("read_file", {})
        assert new_messages[2] == {
            "role": "tool",
            "tool_call_id": "call_bad_json",
            "content": '{"error": "No path provided"}',
        }

    def test_run_conversation_stops_when_max_turns_reached(self):
        """Agent should stop with a clear message when tool-calling exceeds max_turns."""
        repeating_tool_stream = [
            FakeChunk(
                FakeDelta(
                    tool_calls=[
                        FakeToolCallDelta(
                            index=0,
                            call_id="call_repeat",
                            function=FakeFunction(
                                name="read_file",
                                arguments='{"path": "README.md"}',
                            ),
                        )
                    ]
                )
            )
        ]
        streams = [repeating_tool_stream, repeating_tool_stream]

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with patch("astra_claw.agent.loop.OpenAI", return_value=FakeClient(streams)):
                with patch(
                    "astra_claw.agent.loop.registry.dispatch",
                    return_value='{"path": "README.md", "content": "example"}',
                ):
                    agent = AstraAgent(config={"model": {"default": "gpt-5.4-mini", "provider": "openai"}, "agent": {"max_turns": 2}})
                    text, new_messages = agent.run_conversation("loop forever")

        assert text == "Max turns reached. Agent stopped."
        assert len(new_messages) == 5
        assert new_messages[0] == {"role": "user", "content": "loop forever"}
        assert new_messages[-1] == {
            "role": "tool",
            "tool_call_id": "call_repeat",
            "content": '{"path": "README.md", "content": "example"}',
        }
