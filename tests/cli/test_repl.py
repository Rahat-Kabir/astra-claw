from io import StringIO

from rich.console import Console

from astra_claw.cli.repl import run_interactive_repl
from astra_claw.cli.ui import CliUI


class FakePromptSession:
    def __init__(self, prompts):
        self._prompts = list(prompts)

    def prompt(self, *args, **kwargs):
        if not self._prompts:
            raise EOFError
        next_prompt = self._prompts.pop(0)
        if isinstance(next_prompt, BaseException):
            raise next_prompt
        return next_prompt


class FakeAgent:
    def __init__(self):
        self.calls = []

    def run_conversation(self, message, conversation_history=None, stream_writer=None):
        self.calls.append({
            "message": message,
            "history": list(conversation_history or []),
            "stream_writer": stream_writer,
        })
        if stream_writer is not None:
            stream_writer("assistant response")
        return "assistant response", [
            {"role": "user", "content": message},
            {"role": "assistant", "content": "assistant response"},
        ]


def _ui_and_output():
    output = StringIO()
    console = Console(file=output, force_terminal=False, width=100)
    return CliUI(console), output


def test_normal_prompt_calls_agent_with_stream_writer_and_saves_messages():
    agent = FakeAgent()
    saved = []
    ui, output = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        prompt_session=FakePromptSession(["hello", "/exit"]),
        ui=ui,
        save_message_fn=lambda session_id, message: saved.append((session_id, message)),
        patch_stdout_enabled=False,
    )

    assert len(agent.calls) == 1
    assert agent.calls[0]["message"] == "hello"
    assert callable(agent.calls[0]["stream_writer"])
    assert saved == [
        ("session-1", {"role": "user", "content": "hello"}),
        ("session-1", {"role": "assistant", "content": "assistant response"}),
    ]
    assert "assistant response" in output.getvalue()


def test_slash_commands_do_not_call_agent():
    agent = FakeAgent()
    ui, output = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        prompt_session=FakePromptSession(["/help", "/sessions", "/exit"]),
        ui=ui,
        list_sessions_fn=lambda: [{"id": "session-1", "created": "2026-04-15"}],
        patch_stdout_enabled=False,
    )

    rendered = output.getvalue()
    assert agent.calls == []
    assert "/help" in rendered
    assert "session-1" in rendered


def test_new_command_creates_session_and_clears_history_before_next_message():
    agent = FakeAgent()
    saved = []
    ui, _ = _ui_and_output()
    old_history = [{"role": "user", "content": "old"}]

    run_interactive_repl(
        agent=agent,
        session_id="old-session",
        history=old_history,
        prompt_session=FakePromptSession(["/new", "hello", "/exit"]),
        ui=ui,
        create_session_fn=lambda: "new-session",
        save_message_fn=lambda session_id, message: saved.append((session_id, message)),
        patch_stdout_enabled=False,
    )

    assert len(agent.calls) == 1
    assert agent.calls[0]["history"] == []
    assert [session_id for session_id, _ in saved] == ["new-session", "new-session"]


def test_exit_command_exits_cleanly():
    agent = FakeAgent()
    ui, output = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        prompt_session=FakePromptSession(["/quit"]),
        ui=ui,
        patch_stdout_enabled=False,
    )

    assert agent.calls == []
    assert "Bye." in output.getvalue()


def test_plain_exit_still_exits_cleanly():
    agent = FakeAgent()
    ui, output = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        prompt_session=FakePromptSession(["exit"]),
        ui=ui,
        patch_stdout_enabled=False,
    )

    assert agent.calls == []
    assert "Bye." in output.getvalue()
