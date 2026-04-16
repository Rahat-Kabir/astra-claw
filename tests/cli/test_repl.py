from io import StringIO

from rich.console import Console

from astra_claw.agent.context_compactor import CompactionOutcome
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
        self.last_compaction_outcome = None
        self.last_replay_history = []
        self.compact_outcome = None
        self.auto_compact_base_history = None

    def run_conversation(self, message, conversation_history=None, stream_writer=None, *, events=None):
        history = list(conversation_history or [])
        self.calls.append({
            "message": message,
            "history": history,
            "stream_writer": stream_writer,
            "events": events,
        })
        if stream_writer is not None:
            stream_writer("assistant response")
        new_messages = [
            {"role": "user", "content": message},
            {"role": "assistant", "content": "assistant response"},
        ]
        if self.auto_compact_base_history is not None:
            self.last_compaction_outcome = CompactionOutcome(
                did_compact=True,
                messages=list(self.auto_compact_base_history) + new_messages,
                summary_text="summary",
                estimated_tokens_before=200,
                estimated_tokens_after=100,
                dropped_messages=2,
                passes=1,
            )
            self.last_replay_history = list(self.auto_compact_base_history) + new_messages
        else:
            self.last_compaction_outcome = None
            self.last_replay_history = history + new_messages
        return "assistant response", new_messages

    def compact_history(self, history, force=True):
        if self.compact_outcome is not None:
            return self.compact_outcome
        return CompactionOutcome(
            did_compact=False,
            messages=list(history),
            summary_text="",
            estimated_tokens_before=10,
            estimated_tokens_after=10,
            dropped_messages=0,
            passes=0,
        )


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


def test_compact_command_rewrites_session_and_replaces_active_history():
    agent = FakeAgent()
    ui, output = _ui_and_output()
    rewrites = []
    archives = []
    saved = []
    agent.compact_outcome = CompactionOutcome(
        did_compact=True,
        messages=[
            {"role": "assistant", "content": "[CONTEXT COMPACTION]\nsummary"},
        ],
        summary_text="summary",
        estimated_tokens_before=200,
        estimated_tokens_after=100,
        dropped_messages=3,
        passes=1,
    )

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        history=[{"role": "user", "content": "old"}],
        prompt_session=FakePromptSession(["/compact", "hello", "/exit"]),
        ui=ui,
        save_message_fn=lambda session_id, message: saved.append((session_id, message)),
        rewrite_session_fn=lambda session_id, messages, meta_updates=None: rewrites.append((session_id, messages, meta_updates)),
        archive_session_fn=lambda session_id, reason=None: archives.append((session_id, reason)),
        load_session_meta_fn=lambda session_id: {"id": session_id, "compactions": 0},
        patch_stdout_enabled=False,
    )

    assert rewrites[0][0] == "session-1"
    assert rewrites[0][1] == [{"role": "assistant", "content": "[CONTEXT COMPACTION]\nsummary"}]
    assert archives == [("session-1", "manual-compact")]
    assert agent.calls[0]["history"] == [{"role": "assistant", "content": "[CONTEXT COMPACTION]\nsummary"}]
    assert "Compacted context" in output.getvalue()
    assert saved[-2:] == [
        ("session-1", {"role": "user", "content": "hello"}),
        ("session-1", {"role": "assistant", "content": "assistant response"}),
    ]


def test_auto_compaction_rewrites_session_before_saving_new_messages():
    agent = FakeAgent()
    ui, _ = _ui_and_output()
    rewrites = []
    archives = []
    saved = []
    agent.auto_compact_base_history = [
        {"role": "assistant", "content": "[CONTEXT COMPACTION]\nsummary"},
    ]

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        history=[{"role": "user", "content": "old"}],
        prompt_session=FakePromptSession(["hello", "/exit"]),
        ui=ui,
        save_message_fn=lambda session_id, message: saved.append((session_id, message)),
        rewrite_session_fn=lambda session_id, messages, meta_updates=None: rewrites.append((session_id, messages, meta_updates)),
        archive_session_fn=lambda session_id, reason=None: archives.append((session_id, reason)),
        load_session_meta_fn=lambda session_id: {"id": session_id, "compactions": 1},
        patch_stdout_enabled=False,
    )

    assert archives == [("session-1", "auto-compact")]
    assert rewrites[0][1] == [{"role": "assistant", "content": "[CONTEXT COMPACTION]\nsummary"}]
    assert saved == [
        ("session-1", {"role": "user", "content": "hello"}),
        ("session-1", {"role": "assistant", "content": "assistant response"}),
    ]
