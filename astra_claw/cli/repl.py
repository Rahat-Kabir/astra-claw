"""Interactive prompt loop for Astra-Claw."""

from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style

from ..agent.events import AgentEvents
from ..agent.title_generator import maybe_auto_title
from ..constants import get_astraclaw_home
from ..session import (
    archive_session,
    create_session,
    list_sessions,
    load_session_meta,
    rewrite_session,
    save_message,
)
from .commands import resolve_command, SlashCommandCompleter
from .tool_display import build_tool_preview, summarize_tool_result
from .ui import CliUI


def build_prompt_session() -> PromptSession:
    """Create the styled prompt session with persistent input history."""
    history_path = get_astraclaw_home() / ".astraclaw_history"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    return PromptSession(
        history=FileHistory(str(history_path)),
        completer=SlashCommandCompleter(),
        complete_while_typing=True,
        style=Style.from_dict({"prompt": "ansicyan bold"}),
    )


def run_interactive_repl(
    agent: Any,
    session_id: str,
    history: Optional[list[dict]] = None,
    workspace: Optional[Path] = None,
    resumed: bool = False,
    prompt_session: Optional[Any] = None,
    ui: Optional[CliUI] = None,
    create_session_fn: Callable[[], str] = create_session,
    save_message_fn: Callable[[str, dict], None] = save_message,
    list_sessions_fn: Callable[[], list[dict]] = list_sessions,
    rewrite_session_fn: Callable[..., None] = rewrite_session,
    archive_session_fn: Callable[..., Path] = archive_session,
    load_session_meta_fn: Callable[[str], dict] = load_session_meta,
    patch_stdout_enabled: bool = True,
) -> None:
    """Run the interactive CLI loop."""
    active_history = list(history) if history else []
    active_session_id = session_id
    prompt = prompt_session or build_prompt_session()
    cli_ui = ui or CliUI()
    pending_title_threads: list = []

    resumed_title = (
        load_session_meta_fn(active_session_id).get("title") if resumed else None
    )
    cli_ui.print_banner(
        session_id=active_session_id,
        workspace=workspace,
        resumed=resumed,
        loaded_messages=len(active_history),
        title=resumed_title,
    )

    try:
        _run_loop(
            agent=agent,
            active_session_id=active_session_id,
            active_history=active_history,
            prompt=prompt,
            cli_ui=cli_ui,
            pending_title_threads=pending_title_threads,
            create_session_fn=create_session_fn,
            save_message_fn=save_message_fn,
            list_sessions_fn=list_sessions_fn,
            rewrite_session_fn=rewrite_session_fn,
            archive_session_fn=archive_session_fn,
            load_session_meta_fn=load_session_meta_fn,
            patch_stdout_enabled=patch_stdout_enabled,
        )
    finally:
        _join_title_threads(pending_title_threads, cli_ui)


def _join_title_threads(threads: list, cli_ui: "CliUI", per_thread_timeout: float = 5.0) -> None:
    """Wait briefly for in-flight auto-title threads so they can persist before exit."""
    alive = [t for t in threads if t is not None and t.is_alive()]
    if not alive:
        return
    cli_ui.start_thinking("Saving session titles")
    try:
        for t in alive:
            t.join(timeout=per_thread_timeout)
    finally:
        cli_ui.stop_thinking()


def _run_loop(
    *,
    agent,
    active_session_id,
    active_history,
    prompt,
    cli_ui,
    pending_title_threads,
    create_session_fn,
    save_message_fn,
    list_sessions_fn,
    rewrite_session_fn,
    archive_session_fn,
    load_session_meta_fn,
    patch_stdout_enabled,
):
    while True:
        try:
            stdout_context = patch_stdout() if patch_stdout_enabled else nullcontext()
            with stdout_context:
                message = prompt.prompt([("class:prompt", "astra> ")]).strip()
        except (KeyboardInterrupt, EOFError):
            cli_ui.newline()
            cli_ui.print_success("Bye.")
            break

        if not message:
            continue

        if message.lower() in ("exit", "quit"):
            cli_ui.print_success("Bye.")
            break

        command = resolve_command(message)
        if command is not None:
            if command.name == "/help":
                cli_ui.print_help()
            elif command.name == "/sessions":
                cli_ui.print_sessions(list_sessions_fn())
            elif command.name == "/new":
                active_session_id = create_session_fn()
                active_history.clear()
                cli_ui.print_success(f"New session: {active_session_id}")
            elif command.name == "/compact":
                outcome = agent.compact_history(active_history, force=True)
                if not outcome.did_compact:
                    cli_ui.print_warning("Nothing to compact.")
                    continue

                archive_session_fn(active_session_id, reason="manual-compact")
                rewrite_session_fn(
                    active_session_id,
                    outcome.messages,
                    meta_updates=_build_compaction_meta_updates(load_session_meta_fn(active_session_id)),
                )
                active_history = list(outcome.messages)
                cli_ui.print_compaction_result(
                    estimated_tokens_before=outcome.estimated_tokens_before,
                    estimated_tokens_after=outcome.estimated_tokens_after,
                    dropped_messages=outcome.dropped_messages,
                    passes=outcome.passes,
                )
            elif command.name == "/exit":
                cli_ui.print_success("Bye.")
                break
            continue

        events = _build_agent_events(cli_ui)
        clarify_callback = _build_clarify_callback(cli_ui, prompt)
        try:
            response, new_messages = agent.run_conversation(
                message,
                conversation_history=active_history,
                stream_writer=cli_ui.stream_token,
                events=events,
                clarify_callback=clarify_callback,
                current_session_id=active_session_id,
            )
        finally:
            cli_ui.stop_thinking()
        if response:
            cli_ui.newline()

        compaction_outcome = getattr(agent, "last_compaction_outcome", None)
        replay_history = list(getattr(agent, "last_replay_history", []))
        if compaction_outcome is not None and compaction_outcome.did_compact:
            compacted_base_history = replay_history[:-len(new_messages)] if new_messages else replay_history
            archive_session_fn(active_session_id, reason="auto-compact")
            rewrite_session_fn(
                active_session_id,
                compacted_base_history,
                meta_updates=_build_compaction_meta_updates(load_session_meta_fn(active_session_id)),
            )
            active_history = list(compacted_base_history)
            cli_ui.print_compaction_result(
                estimated_tokens_before=compaction_outcome.estimated_tokens_before,
                estimated_tokens_after=compaction_outcome.estimated_tokens_after,
                dropped_messages=compaction_outcome.dropped_messages,
                passes=compaction_outcome.passes,
            )

        for msg in new_messages:
            save_message_fn(active_session_id, msg)
        active_history.extend(new_messages)

        title_thread = _maybe_schedule_auto_title(
            agent=agent,
            session_id=active_session_id,
            user_message=message,
            assistant_response=response or "",
            history=active_history,
        )
        if title_thread is not None:
            pending_title_threads.append(title_thread)


def _build_agent_events(cli_ui: CliUI) -> AgentEvents:
    """Wire a CliUI into the three agent hooks for spinner + tool feedback."""

    def on_thinking(active: bool) -> None:
        if active:
            cli_ui.start_thinking("Thinking")
        else:
            cli_ui.stop_thinking()

    def on_tool_start(call_id: str, name: str, args: dict) -> None:
        preview = build_tool_preview(name, args)
        label = f"Running {name}"
        if preview:
            label += f" {preview}"
        cli_ui.start_thinking(label)

    def on_tool_complete(call_id: str, name: str, args: dict, result: str) -> None:
        cli_ui.stop_thinking()
        preview = build_tool_preview(name, args)
        summary = summarize_tool_result(name, result)
        cli_ui.print_tool_line(name, preview, summary)

    return AgentEvents(
        on_thinking=on_thinking,
        on_tool_start=on_tool_start,
        on_tool_complete=on_tool_complete,
    )


def _build_clarify_callback(
    cli_ui: CliUI,
    prompt_session: Any,
) -> Callable[[str, Optional[List[str]]], str]:
    """Return a callback that renders the clarify prompt and reads one answer.

    Numeric input within range resolves to the matching choice text; anything
    else (including the implicit "Other" option) is returned verbatim.
    """

    def _clarify(question: str, choices: Optional[List[str]]) -> str:
        cli_ui.stop_thinking()
        cli_ui.print_clarify_question(question, choices)
        try:
            answer = prompt_session.prompt([("class:prompt", "answer> ")]).strip()
        except (KeyboardInterrupt, EOFError):
            return ""

        if choices and answer.isdigit():
            index = int(answer)
            if 1 <= index <= len(choices):
                return choices[index - 1]
        return answer

    return _clarify


def _maybe_schedule_auto_title(
    *,
    agent: Any,
    session_id: str,
    user_message: str,
    assistant_response: str,
    history: list[dict],
):
    """Fire the auto-title daemon after a user-facing turn, if eligible.

    Returns the spawned Thread (so the REPL can join it on exit) or None.
    """
    config = getattr(agent, "config", {}) or {}
    session_cfg = config.get("session", {}) or {}
    if not session_cfg.get("auto_title", True):
        return None
    if not assistant_response:
        return None

    route = getattr(agent, "primary_route", None) or {}
    provider = route.get("provider")
    if not provider:
        return None
    summary_model = (config.get("compression", {}) or {}).get("summary_model")
    model = summary_model or route.get("model")
    if not model:
        return None

    user_msg_count = sum(1 for m in history if m.get("role") == "user")
    return maybe_auto_title(
        session_id,
        user_message,
        assistant_response,
        user_msg_count=user_msg_count,
        provider=provider,
        model=model,
        enabled=True,
    )


def _build_compaction_meta_updates(meta: dict) -> dict:
    timestamp = datetime.now().isoformat()
    return {
        "updated": timestamp,
        "compactions": int(meta.get("compactions", 0)) + 1,
        "last_compacted_at": timestamp,
    }
