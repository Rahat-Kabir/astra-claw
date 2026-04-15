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
    """Returns predefined streams one call at a time."""

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


class FakeLlmError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class FailingCompletions:
    def __init__(self, failures):
        self._failures = list(failures)

    def create(self, **kwargs):
        raise self._failures.pop(0)


class FailingClient:
    def __init__(self, failures):
        self.chat = types.SimpleNamespace(completions=FailingCompletions(failures))


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
            with patch("astra_claw.agent.loop.create_client", return_value=FakeClient(streams)):
                agent = AstraAgent()
                text, new_messages = agent.run_conversation("hi")

        assert text == "Hello world"
        assert new_messages == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "Hello world"},
        ]

    def test_run_conversation_streams_to_callback_when_provided(self):
        """Agent should send streamed text through the caller-provided callback."""
        streams = [
            [
                FakeChunk(FakeDelta(content="Hello")),
                FakeChunk(FakeDelta(content=" callback")),
            ]
        ]
        tokens = []

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with patch("astra_claw.agent.loop.create_client", return_value=FakeClient(streams)):
                agent = AstraAgent()
                text, _ = agent.run_conversation("hi", stream_writer=tokens.append)

        assert text == "Hello callback"
        assert tokens == ["Hello", " callback"]

    def test_run_conversation_uses_stdout_when_no_callback(self, capsys):
        """Agent should preserve the old stdout streaming behavior by default."""
        streams = [
            [
                FakeChunk(FakeDelta(content="Hello")),
                FakeChunk(FakeDelta(content=" stdout")),
            ]
        ]

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with patch("astra_claw.agent.loop.create_client", return_value=FakeClient(streams)):
                agent = AstraAgent()
                text, _ = agent.run_conversation("hi")

        assert text == "Hello stdout"
        assert capsys.readouterr().out == "Hello stdout"

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
        final_text_stream = [FakeChunk(FakeDelta(content="Done reading file."))]
        streams = [tool_call_stream, final_text_stream]

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with patch("astra_claw.agent.loop.create_client", return_value=FakeClient(streams)):
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
                                arguments='{"path": "README.md"',
                            ),
                        )
                    ]
                )
            )
        ]
        final_text_stream = [FakeChunk(FakeDelta(content="Handled invalid args."))]
        streams = [tool_call_stream, final_text_stream]

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with patch("astra_claw.agent.loop.create_client", return_value=FakeClient(streams)):
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
            with patch("astra_claw.agent.loop.create_client", return_value=FakeClient(streams)):
                with patch(
                    "astra_claw.agent.loop.registry.dispatch",
                    return_value='{"path": "README.md", "content": "example"}',
                ):
                    agent = AstraAgent(
                        config={
                            "model": {"default": "gpt-5.4-mini", "provider": "openai"},
                            "agent": {"max_turns": 2},
                        }
                    )
                    text, new_messages = agent.run_conversation("loop forever")

        assert text == "Max turns reached. Agent stopped."
        assert len(new_messages) == 5
        assert new_messages[0] == {"role": "user", "content": "loop forever"}
        assert new_messages[-1] == {
            "role": "tool",
            "tool_call_id": "call_repeat",
            "content": '{"path": "README.md", "content": "example"}',
        }

    def test_run_conversation_falls_back_on_transient_primary_error(self):
        final_text_stream = [FakeChunk(FakeDelta(content="Recovered via fallback."))]
        clients = {
            "openai": FailingClient([FakeLlmError("connection reset by peer")]),
            "openrouter": FakeClient([final_text_stream]),
        }

        with patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "test-key", "OPENROUTER_API_KEY": "fallback-key"},
        ):
            with patch(
                "astra_claw.agent.loop.create_client",
                side_effect=lambda provider: clients[provider],
            ):
                agent = AstraAgent()
                text, new_messages = agent.run_conversation("hi")

        assert text == "Recovered via fallback."
        assert new_messages == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "Recovered via fallback."},
        ]

    def test_run_conversation_does_not_fall_back_on_bad_request(self):
        clients = {
            "openai": FailingClient([FakeLlmError("bad request", status_code=400)]),
        }

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with patch(
                "astra_claw.agent.loop.create_client",
                side_effect=lambda provider: clients[provider],
            ):
                agent = AstraAgent()
                try:
                    agent.run_conversation("hi")
                    assert False, "Expected primary bad request to propagate."
                except FakeLlmError as exc:
                    assert exc.status_code == 400

    def test_run_conversation_raises_when_fallback_client_creation_fails(self):
        clients = {
            "openai": FailingClient([FakeLlmError("timeout while connecting")]),
        }

        def create_client_side_effect(provider):
            if provider == "openrouter":
                raise RuntimeError("No API key found. Set OPENROUTER_API_KEY environment variable.")
            return clients[provider]

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with patch(
                "astra_claw.agent.loop.create_client",
                side_effect=create_client_side_effect,
            ):
                agent = AstraAgent()
                try:
                    agent.run_conversation("hi")
                    assert False, "Expected fallback client creation failure to propagate."
                except RuntimeError as exc:
                    assert "OPENROUTER_API_KEY" in str(exc)
