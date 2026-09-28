from io import StringIO
import asyncio
import threading
from unittest.mock import patch

import pytest
from rich.console import Console

from astra_claw import constants
from astra_claw.agent.context_compactor import CompactionOutcome, CompactionConfig, ContextCompactor
from astra_claw.cli.repl import run_interactive_repl
from astra_claw.cli.ui import CliUI


@pytest.fixture(autouse=True)
def _reset_fence():
    constants._workspace_fence = None
    yield
    constants._workspace_fence = None


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


def _prompt_text(message):
    if isinstance(message, list):
        return "".join(part[1] for part in message)
    return str(message)


class AsyncFollowUpPromptSession(FakePromptSession):
    def __init__(self, prompts, *, started, release):
        super().__init__(prompts)
        self.started = started
        self.release = release
        self.followup_sent = False
        self.async_prompt_kwargs = []

    async def prompt_async(self, message, **kwargs):
        self.async_prompt_kwargs.append(kwargs)
        text = _prompt_text(message)
        if text.startswith("follow-up>") and not self.followup_sent:
            while not self.started.is_set():
                await asyncio.sleep(0.001)
            self.followup_sent = True
            self.release.set()
            return "run the tests too"
        await asyncio.Future()


class AsyncApprovalPromptSession(FakePromptSession):
    async def prompt_async(self, message, **kwargs):
        if _prompt_text(message).startswith("apply write?"):
            return "y"
        await asyncio.Future()


class AsyncClarifyPromptSession(FakePromptSession):
    async def prompt_async(self, message, **kwargs):
        if _prompt_text(message).startswith("answer>"):
            return "1"
        await asyncio.Future()


class AsyncSteeringPromptSession(FakePromptSession):
    def __init__(self, prompts, *, started):
        super().__init__(prompts)
        self.started = started
        self.steering_sent = False

    async def prompt_async(self, message, **kwargs):
        text = _prompt_text(message)
        if text.startswith("follow-up>") and not self.steering_sent:
            while not self.started.is_set():
                await asyncio.sleep(0.001)
            self.steering_sent = True
            return "/steering stop editing and run tests first"
        await asyncio.Future()


class AsyncLateSteeringPromptSession(FakePromptSession):
    def __init__(self, prompts, *, finishing):
        super().__init__(prompts)
        self.finishing = finishing
        self.steering_sent = False

    async def prompt_async(self, message, **kwargs):
        text = _prompt_text(message)
        if text.startswith("follow-up>") and not self.steering_sent:
            while not self.finishing.is_set():
                await asyncio.sleep(0.001)
            self.steering_sent = True
            return "/steer run tests before finishing"
        await asyncio.Future()


class FakeAgent:
    def __init__(self):
        self.config = {"cli": {"render_markdown": False}}
        self.calls = []
        self.last_compaction_outcome = None
        self.last_replay_history = []
        self.compact_outcome = None
        self.auto_compact_base_history = None

    def run_conversation(
        self,
        message,
        conversation_history=None,
        stream_writer=None,
        *,
        events=None,
        clarify_callback=None,
        current_session_id=None,
        steering_reader=None,
    ):
        history = list(conversation_history or [])
        self.calls.append({
            "message": message,
            "history": history,
            "stream_writer": stream_writer,
            "events": events,
            "clarify_callback": clarify_callback,
            "current_session_id": current_session_id,
            "steering_reader": steering_reader,
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


class BlockingFirstAgent(FakeAgent):
    def __init__(self, started, release):
        super().__init__()
        self.started = started
        self.release = release

    def run_conversation(self, *args, **kwargs):
        if not self.calls:
            self.started.set()
            assert self.release.wait(timeout=2)
        return super().run_conversation(*args, **kwargs)


class ApprovalAgent(FakeAgent):
    def run_conversation(self, *args, **kwargs):
        from astra_claw.tools.path_safety import request_write_approval

        assert request_write_approval("note.txt", "diff", "write") is True
        return super().run_conversation(*args, **kwargs)


class ClarifyAgent(FakeAgent):
    def __init__(self):
        super().__init__()
        self.answer = None

    def run_conversation(self, *args, **kwargs):
        clarify_callback = kwargs.get("clarify_callback")
        self.answer = clarify_callback("Choose one", ["first", "second"])
        return super().run_conversation(*args, **kwargs)


class SteeringAgent(FakeAgent):
    def __init__(self, started):
        super().__init__()
        self.started = started
        self.steering_message = None

    def run_conversation(self, message, conversation_history=None, **kwargs):
        steering_reader = kwargs["steering_reader"]
        self.calls.append({"message": message})
        self.started.set()
        for _ in range(200):
            self.steering_message = steering_reader()
            if self.steering_message is not None:
                break
            threading.Event().wait(0.005)
        assert self.steering_message is not None
        new_messages = [
            {"role": "user", "content": message},
            {
                "role": "user",
                "content": f"[steering]\n{self.steering_message}",
            },
            {"role": "assistant", "content": "redirected"},
        ]
        self.last_replay_history = list(conversation_history or []) + new_messages
        return "redirected", new_messages


class UnconsumedSteeringAgent(FakeAgent):
    def __init__(self, finishing):
        super().__init__()
        self.finishing = finishing

    def run_conversation(self, *args, **kwargs):
        if not self.calls:
            self.finishing.set()
            threading.Event().wait(0.02)
        return super().run_conversation(*args, **kwargs)


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
    assert agent.calls[0]["current_session_id"] == "session-1"
    assert saved == [
        ("session-1", {"role": "user", "content": "hello"}),
        ("session-1", {"role": "assistant", "content": "assistant response"}),
    ]
    assert "assistant response" in output.getvalue()


def test_followup_is_queued_while_agent_runs_then_processed():
    started = threading.Event()
    release = threading.Event()
    agent = BlockingFirstAgent(started, release)
    prompt = AsyncFollowUpPromptSession(
        ["start the task", "/exit"],
        started=started,
        release=release,
    )
    saved = []
    ui, output = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        prompt_session=prompt,
        ui=ui,
        save_message_fn=lambda session_id, message: saved.append((session_id, message)),
        patch_stdout_enabled=False,
    )

    assert [call["message"] for call in agent.calls] == [
        "start the task",
        "run the tests too",
    ]
    assert agent.calls[1]["history"] == [message for _, message in saved[:2]]
    assert [message["content"] for _, message in saved] == [
        "start the task",
        "assistant response",
        "run the tests too",
        "assistant response",
    ]
    assert "Queued follow-up (1)." in output.getvalue()
    assert "Running queued follow-up." in output.getvalue()
    assert prompt.async_prompt_kwargs
    assert all(call["refresh_interval"] == 0.5 for call in prompt.async_prompt_kwargs)
    assert all(call["bottom_toolbar"] == ui.heartbeat_text for call in prompt.async_prompt_kwargs)
    assert ui._prompt_owns_live_rendering is False


def test_followup_prompt_yields_to_write_approval():
    agent = ApprovalAgent()
    prompt = AsyncApprovalPromptSession(["edit the file", "/exit"])
    ui, output = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        prompt_session=prompt,
        ui=ui,
        patch_stdout_enabled=False,
    )

    assert len(agent.calls) == 1
    assert "assistant response" in output.getvalue()


def test_followup_prompt_yields_to_clarify_question():
    agent = ClarifyAgent()
    prompt = AsyncClarifyPromptSession(["start", "/exit"])
    ui, output = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        prompt_session=prompt,
        ui=ui,
        patch_stdout_enabled=False,
    )

    assert agent.answer == "first"
    assert len(agent.calls) == 1
    assert "Choose one" in output.getvalue()


def test_explicit_steer_is_delivered_inside_the_active_agent_turn():
    started = threading.Event()
    agent = SteeringAgent(started)
    prompt = AsyncSteeringPromptSession(["start", "/exit"], started=started)
    saved = []
    ui, output = _ui_and_output()
    steering_states = []
    original_set_steering_status = ui.set_steering_status

    def record_steering_status(status):
        steering_states.append(status)
        original_set_steering_status(status)

    ui.set_steering_status = record_steering_status

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        prompt_session=prompt,
        ui=ui,
        save_message_fn=lambda session_id, message: saved.append((session_id, message)),
        patch_stdout_enabled=False,
    )

    assert len(agent.calls) == 1
    assert agent.steering_message == "stop editing and run tests first"
    assert [message["content"] for _, message in saved] == [
        "start",
        "[steering]\nstop editing and run tests first",
        "redirected",
    ]
    assert "Queued steering (1)." in output.getvalue()
    assert "steering queued (1)" in steering_states
    assert "steering applied" in steering_states
    assert steering_states.index("steering queued (1)") < steering_states.index(
        "steering applied"
    )


def test_steer_at_idle_shows_busy_only_warning_and_skips_agent():
    agent = FakeAgent()
    ui, output = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        prompt_session=FakePromptSession(
            ["/steering change direction", "/exit"]
        ),
        ui=ui,
        patch_stdout_enabled=False,
    )

    assert agent.calls == []
    assert "Steering is available only while Astra is working." in output.getvalue()


def test_steering_missed_by_final_boundary_runs_as_next_turn():
    finishing = threading.Event()
    agent = UnconsumedSteeringAgent(finishing)
    prompt = AsyncLateSteeringPromptSession(
        ["start", "/exit"],
        finishing=finishing,
    )
    ui, output = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        prompt_session=prompt,
        ui=ui,
        patch_stdout_enabled=False,
    )

    assert [call["message"] for call in agent.calls] == [
        "start",
        "run tests before finishing",
    ]
    assert "Running undelivered steering as the next turn." in output.getvalue()


def test_patch_stdout_preserves_ansi_and_async_context_starts_inside_event_loop():
    calls = []

    class FakeStdoutContext:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def fake_patch_stdout(*, raw=False):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            loop_running = False
        else:
            loop_running = True
        calls.append((raw, loop_running))
        return FakeStdoutContext()

    agent = FakeAgent()
    prompt = AsyncApprovalPromptSession(["start", "/exit"])
    ui, _ = _ui_and_output()

    with patch("astra_claw.cli.repl.patch_stdout", side_effect=fake_patch_stdout):
        run_interactive_repl(
            agent=agent,
            session_id="session-1",
            prompt_session=prompt,
            ui=ui,
            patch_stdout_enabled=True,
        )

    assert calls
    assert all(raw is True for raw, _ in calls)
    assert (True, True) in calls


def test_prompt_context_refs_are_expanded_before_agent_call(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    constants.set_workspace_fence(tmp_path)
    (tmp_path / "note.txt").write_text("attached context", encoding="utf-8")
    agent = FakeAgent()
    saved = []
    ui, _ = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        prompt_session=FakePromptSession(["Read @file:note.txt", "/exit"]),
        ui=ui,
        save_message_fn=lambda session_id, message: saved.append((session_id, message)),
        patch_stdout_enabled=False,
    )

    assert len(agent.calls) == 1
    assert "--- Attached Context ---" in agent.calls[0]["message"]
    assert "attached context" in agent.calls[0]["message"]
    assert saved[0][1]["content"] == agent.calls[0]["message"]


def test_prompt_folder_with_multiple_images_asks_and_attaches_choice(tmp_path, monkeypatch):
    folder = tmp_path / "photos"
    folder.mkdir()
    (folder / "a.png").write_bytes(b"\x89PNG\r\n\x1a\nimage-a")
    (folder / "b.jpg").write_bytes(b"\xff\xd8\xffimage-b")
    agent = FakeAgent()
    saved = []
    ui, output = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        prompt_session=FakePromptSession(
            [f"Tell me what is in {folder}", "2", "/exit"]
        ),
        ui=ui,
        save_message_fn=lambda session_id, message: saved.append((session_id, message)),
        patch_stdout_enabled=False,
    )

    content = agent.calls[0]["message"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert "b.jpg" in content[0]["text"]
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert saved[0][1]["content"] == content
    assert "Which image" in output.getvalue()


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


def test_skills_command_lists_installed_skills(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    skill_dir = tmp_path / "skills" / "code-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: code-review
description: Review code changes.
---
""",
        encoding="utf-8",
    )
    agent = FakeAgent()
    ui, output = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        prompt_session=FakePromptSession(["/skills", "/exit"]),
        ui=ui,
        patch_stdout_enabled=False,
    )

    rendered = output.getvalue()
    assert agent.calls == []
    assert "Installed Skills" in rendered
    assert "code-review" in rendered
    assert "Review code changes." in rendered


def test_skill_command_loads_skill_and_calls_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    skill_dir = tmp_path / "skills" / "code-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: code-review
description: Review code changes.
---

# Code Review

Start with findings.
""",
        encoding="utf-8",
    )
    agent = FakeAgent()
    saved = []
    ui, _ = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        prompt_session=FakePromptSession(["/skill code-review review this", "/exit"]),
        ui=ui,
        save_message_fn=lambda session_id, message: saved.append((session_id, message)),
        patch_stdout_enabled=False,
    )

    assert len(agent.calls) == 1
    message = agent.calls[0]["message"]
    assert 'The user invoked the "code-review" skill' in message
    assert "<skill name=\"code-review\">" in message
    assert "Start with findings." in message
    assert "User request:\nreview this" in message
    assert saved[0][1]["content"] == message


def test_skill_alias_loads_skill_and_calls_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    skill_dir = tmp_path / "skills" / "code-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: code-review
description: Review code changes.
---

# Code Review

Start with findings.
""",
        encoding="utf-8",
    )
    agent = FakeAgent()
    saved = []
    ui, output = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        prompt_session=FakePromptSession(["/code-review review this", "/exit"]),
        ui=ui,
        save_message_fn=lambda session_id, message: saved.append((session_id, message)),
        patch_stdout_enabled=False,
    )

    assert len(agent.calls) == 1
    message = agent.calls[0]["message"]
    assert 'The user invoked the "code-review" skill' in message
    assert "User request:\nreview this" in message
    assert saved[0][1]["content"] == message
    assert "Loading skill: code-review" in output.getvalue()


def test_skill_alias_without_request_calls_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    skill_dir = tmp_path / "skills" / "code-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: code-review
description: Review code changes.
---
""",
        encoding="utf-8",
    )
    agent = FakeAgent()
    ui, _ = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        prompt_session=FakePromptSession(["/code-review", "/exit"]),
        ui=ui,
        patch_stdout_enabled=False,
    )

    assert len(agent.calls) == 1
    assert 'The user invoked the "code-review" skill' in agent.calls[0]["message"]
    assert "User request:" not in agent.calls[0]["message"]


def test_skill_command_missing_args_does_not_call_agent():
    agent = FakeAgent()
    ui, output = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        prompt_session=FakePromptSession(["/skill code-review", "/exit"]),
        ui=ui,
        patch_stdout_enabled=False,
    )

    assert agent.calls == []
    assert "Usage: /skill <name> <request>" in output.getvalue()


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


class TitleAgent(FakeAgent):
    def __init__(self):
        super().__init__()
        self.config = {
            "session": {"auto_title": True},
            "compression": {"summary_model": None},
        }
        self.primary_route = {"provider": "openai", "model": "gpt-x"}


def test_auto_title_fires_after_first_exchange():
    agent = TitleAgent()
    ui, _ = _ui_and_output()
    calls = []

    with patch(
        "astra_claw.cli.repl.maybe_auto_title",
        side_effect=lambda *args, **kwargs: calls.append((args, kwargs)),
    ):
        run_interactive_repl(
            agent=agent,
            session_id="session-1",
            prompt_session=FakePromptSession(["hello", "/exit"]),
            ui=ui,
            save_message_fn=lambda session_id, message: None,
            patch_stdout_enabled=False,
        )

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == "session-1"
    assert args[1] == "hello"
    assert args[2] == "assistant response"
    assert kwargs["provider"] == "openai"
    assert kwargs["model"] == "gpt-x"
    assert kwargs["user_msg_count"] == 1


def test_auto_title_skipped_when_config_disables_it():
    agent = TitleAgent()
    agent.config["session"]["auto_title"] = False
    ui, _ = _ui_and_output()
    calls = []

    with patch(
        "astra_claw.cli.repl.maybe_auto_title",
        side_effect=lambda *args, **kwargs: calls.append(args),
    ):
        run_interactive_repl(
            agent=agent,
            session_id="session-1",
            prompt_session=FakePromptSession(["hello", "/exit"]),
            ui=ui,
            save_message_fn=lambda session_id, message: None,
            patch_stdout_enabled=False,
        )

    assert calls == []


def test_auto_title_uses_summary_model_when_set():
    agent = TitleAgent()
    agent.config["compression"]["summary_model"] = "cheap-model"
    ui, _ = _ui_and_output()
    calls = []

    with patch(
        "astra_claw.cli.repl.maybe_auto_title",
        side_effect=lambda *args, **kwargs: calls.append(kwargs),
    ):
        run_interactive_repl(
            agent=agent,
            session_id="session-1",
            prompt_session=FakePromptSession(["hello", "/exit"]),
            ui=ui,
            save_message_fn=lambda session_id, message: None,
            patch_stdout_enabled=False,
        )

    assert calls[0]["model"] == "cheap-model"


class UsageFakeAgent:
    primary_route = {"provider": "openai", "model": "gpt-test"}
    compression_enabled = True
    memory_store = None
    calls = []

    def __init__(self):
        self.compactor = ContextCompactor(
            CompactionConfig(
                context_window=128000,
                threshold_ratio=0.80,
                reserve_tokens=4000,
                keep_first_n=2,
                keep_last_n=6,
                max_passes=2,
            )
        )

    def get_system_prompt_text(self):
        return "system prompt"

    def run_conversation(self, *args, **kwargs):
        self.calls.append("run")
        return "hi", []


def test_usage_command_does_not_call_agent():
    agent = UsageFakeAgent()
    ui, output = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-usage",
        prompt_session=FakePromptSession(["/usage", "/exit"]),
        ui=ui,
        load_session_meta_fn=lambda session_id: {"id": session_id, "compactions": 0},
        patch_stdout_enabled=False,
    )

    assert agent.calls == []
    assert "Usage" in output.getvalue()
    assert "Context" in output.getvalue()


def test_markdown_mode_renders_assistant_reply_without_raw_stars():
    class MarkdownAgent(FakeAgent):
        def run_conversation(
            self,
            message,
            conversation_history=None,
            stream_writer=None,
            *,
            events=None,
            clarify_callback=None,
            current_session_id=None,
        ):
            if stream_writer is not None:
                stream_writer("**Hello**")
            return "**Hello**", [
                {"role": "user", "content": message},
                {"role": "assistant", "content": "**Hello**"},
            ]

    agent = MarkdownAgent()
    agent.config = {"cli": {"render_markdown": True}}
    ui, output = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-md",
        prompt_session=FakePromptSession(["hi", "/exit"]),
        ui=ui,
        save_message_fn=lambda session_id, message: None,
        patch_stdout_enabled=False,
    )

    rendered = output.getvalue()
    assert "**Hello**" not in rendered
    assert "Hello" in rendered


def test_retry_rewrites_session_and_reruns_last_user_message():
    agent = FakeAgent()
    ui, output = _ui_and_output()
    rewrites = []
    archives = []
    history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": "a2"},
    ]

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        history=history,
        prompt_session=FakePromptSession(["/retry", "/exit"]),
        ui=ui,
        save_message_fn=lambda session_id, message: None,
        rewrite_session_fn=lambda session_id, messages, meta_updates=None: rewrites.append(
            (session_id, messages, meta_updates)
        ),
        archive_session_fn=lambda session_id, reason=None: archives.append((session_id, reason)),
        patch_stdout_enabled=False,
    )

    assert archives == [("session-1", "retry")]
    assert rewrites[0][0] == "session-1"
    assert rewrites[0][1] == history[:2]
    assert len(agent.calls) == 1
    assert agent.calls[0]["message"] == "second"
    assert agent.calls[0]["history"] == history[:2]
    assert "Retrying last prompt" in output.getvalue()


def test_retry_with_empty_history_shows_warning():
    agent = FakeAgent()
    ui, output = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        history=[],
        prompt_session=FakePromptSession(["/retry", "/exit"]),
        ui=ui,
        patch_stdout_enabled=False,
    )

    assert agent.calls == []
    assert "Nothing to retry." in output.getvalue()


# ---------------------------------------------------------------------------
# /undo
# ---------------------------------------------------------------------------

def test_undo_with_empty_stack_warns_and_skips_agent():
    from astra_claw.tools import path_safety

    agent = FakeAgent()
    ui, output = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        prompt_session=FakePromptSession(["/undo", "/exit"]),
        ui=ui,
        patch_stdout_enabled=False,
    )

    assert agent.calls == []
    assert "Nothing to undo." in output.getvalue()
    assert path_safety._undo_stack == []


def test_repl_startup_clears_undo_stack():
    from astra_claw.tools import path_safety

    path_safety.record_undo("stale.txt", "old", True, "new")
    agent = FakeAgent()
    ui, output = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        prompt_session=FakePromptSession(["/undo", "/exit"]),
        ui=ui,
        patch_stdout_enabled=False,
    )

    assert agent.calls == []
    assert "Nothing to undo." in output.getvalue()


def test_undo_restores_file_and_notifies_model(tmp_path, monkeypatch):
    from astra_claw.tools import path_safety

    monkeypatch.chdir(tmp_path)
    constants.set_workspace_fence(tmp_path)
    target = tmp_path / "note.txt"
    target.write_text("old", encoding="utf-8")
    path_safety.record_undo(str(target), "old", True, "new")
    target.write_text("new", encoding="utf-8")
    # Pre-seeded entry: bypass the (correct) startup wipe for this test.
    monkeypatch.setattr("astra_claw.cli.repl.clear_undo", lambda: None)

    agent = FakeAgent()
    saved = []
    ui, output = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        prompt_session=FakePromptSession(["/undo", "hello", "/exit"]),
        ui=ui,
        save_message_fn=lambda session_id, message: saved.append((session_id, message)),
        patch_stdout_enabled=False,
    )

    assert target.read_text(encoding="utf-8") == "old"
    undo_notes = [msg for _, msg in saved if msg["content"].startswith("[undo]")]
    assert len(undo_notes) == 1
    assert "Reverted the last approved write" in undo_notes[0]["content"]
    # The note reaches the agent as the newest history message.
    assert agent.calls[0]["history"][-1]["content"].startswith("[undo]")
    assert "Reverted:" in output.getvalue()


def test_undo_refusal_saves_no_note(tmp_path, monkeypatch):
    from astra_claw.tools import path_safety

    monkeypatch.chdir(tmp_path)
    constants.set_workspace_fence(tmp_path)
    target = tmp_path / "gone.txt"
    path_safety.record_undo(str(target), "old", True, "new")
    monkeypatch.setattr("astra_claw.cli.repl.clear_undo", lambda: None)

    agent = FakeAgent()
    saved = []
    ui, output = _ui_and_output()

    run_interactive_repl(
        agent=agent,
        session_id="session-1",
        prompt_session=FakePromptSession(["/undo", "/exit"]),
        ui=ui,
        save_message_fn=lambda session_id, message: saved.append((session_id, message)),
        patch_stdout_enabled=False,
    )

    assert agent.calls == []
    assert saved == []
    assert "Not undoing" in output.getvalue()
    # Refused undo keeps its entry for a later retry.
    assert len(path_safety._undo_stack) == 1
