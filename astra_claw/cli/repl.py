"""Interactive prompt loop for Astra-Claw."""

import asyncio
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
from ..config import save_user_config
from ..llm import format_route_label, resolve_api_key, validate_credentials
from ..session import (
    archive_session,
    create_session,
    list_sessions,
    load_session_meta,
    message_content_text,
    rewrite_session,
    save_message,
)
from ..tools.path_safety import clear_undo, set_write_approval_callback, undo_last_write
from .commands import resolve_command, parse_model_arg, AstraCompleter
from .context_refs import expand_context_references
from .followup import FollowUpQueue, PromptBroker
from .history_edit import truncate_for_retry
from .image_attachments import prepare_image_prompt
from .skills import build_skill_invocation_message, list_skills, resolve_skill_command
from .tool_display import build_tool_preview, summarize_tool_result
from .ui import CliUI
from .usage import build_usage_snapshot


def build_prompt_session() -> PromptSession:
    """Create the styled prompt session with persistent input history."""
    history_path = get_astraclaw_home() / ".astraclaw_history"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    return PromptSession(
        history=FileHistory(str(history_path)),
        completer=AstraCompleter(),
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
    write_approval_state = {"always": False}

    resumed_title = (
        load_session_meta_fn(active_session_id).get("title") if resumed else None
    )
    model_label = format_route_label(getattr(agent, "primary_route", None))
    cli_ui.print_banner(
        session_id=active_session_id,
        workspace=workspace,
        resumed=resumed,
        loaded_messages=len(active_history),
        title=resumed_title,
        model=model_label or None,
    )

    clear_undo()
    if _confirm_edits_enabled(agent):
        set_write_approval_callback(
            _build_write_approval_callback(
                cli_ui,
                prompt,
                state=write_approval_state,
            )
        )
    else:
        set_write_approval_callback(None)

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
            write_approval_state=write_approval_state,
        )
    finally:
        set_write_approval_callback(None)
        _join_title_threads(pending_title_threads, cli_ui)


def _save_undo_note(
    save_message_fn: Callable[[str, dict], None],
    session_id: str,
    history: list[dict],
    text: str,
) -> None:
    """Persist a synthetic [undo] user message so the model learns the file
    world changed — without it, a stale full-file rewrite would silently
    re-apply the write the user just reverted."""
    note = {"role": "user", "content": text}
    history.append(note)
    save_message_fn(session_id, note)


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
    write_approval_state,
):
    prompt_default = ""
    while True:
        try:
            stdout_context = patch_stdout() if patch_stdout_enabled else nullcontext()
            with stdout_context:
                message = prompt.prompt(
                    [("class:prompt", "astra> ")],
                    default=prompt_default,
                ).strip()
            prompt_default = ""
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
            elif command.name == "/usage":
                snapshot = build_usage_snapshot(
                    agent=agent,
                    session_id=active_session_id,
                    history=active_history,
                    session_meta=load_session_meta_fn(active_session_id),
                    heartbeat=cli_ui.get_heartbeat_snapshot(),
                )
                cli_ui.print_usage_panel(snapshot)

            elif command.name == "/model":
                parts = message.split(maxsplit=1)
                arg = parts[1].strip() if len(parts) > 1 else ""

                if not arg:
                    cli_ui.print_model_info(
                        current=format_route_label(getattr(agent, "primary_route", None)),
                        fallback=format_route_label(getattr(agent, "fallback_route", None)),
                    )
                    continue

                current_route = getattr(agent, "primary_route", None) or {}
                try:
                    provider, model = parse_model_arg(arg, current_route.get("provider", "openai"))
                except ValueError:
                    cli_ui.print_warning("Usage: /model openai:gpt-4o   (or just /model gpt-4o)")
                    continue

                api_key = resolve_api_key(provider, getattr(agent, "model_config", None) or {})
                if not api_key:
                    cli_ui.print_warning(
                        f"No API key for '{provider}'. Run 'astraclaw setup key' first."
                    )
                    continue

                cli_ui.start_thinking(f"validating {provider}")
                ok, detail = validate_credentials(provider, api_key)
                cli_ui.stop_thinking()
                if not ok:
                    cli_ui.print_warning(f"Could not switch to {provider}:{model} — {detail}")
                    continue

                try:
                    agent.set_primary_route(provider, model)
                    save_user_config({"model": {"provider": provider, "default": model}})
                except Exception as exc:
                    cli_ui.print_error(f"Switch failed: {exc}")
                    continue

                cli_ui.print_success(
                    f"Model switched to {format_route_label(agent.primary_route)} (saved)."
                )
                continue

            elif command.name == "/retry":
                truncated, user_text = truncate_for_retry(active_history)
                if user_text is None:
                    cli_ui.print_warning("Nothing to retry.")
                    continue

                archive_session_fn(active_session_id, reason="retry")
                rewrite_session_fn(active_session_id, truncated)
                active_history = list(truncated)
                message = user_text
                cli_ui.print_success("Retrying last prompt…")
            elif command.name == "/undo":
                result = undo_last_write()
                if result.status == "empty":
                    cli_ui.print_warning("Nothing to undo.")
                elif result.status == "restored":
                    cli_ui.print_success(f"Reverted: {result.path}")
                    _save_undo_note(
                        save_message_fn,
                        active_session_id,
                        active_history,
                        f"[undo] Reverted the last approved write to {result.path}; "
                        "the file is back to its previous state.",
                    )
                elif result.status == "removed":
                    cli_ui.print_success(f"Removed: {result.path}")
                    _save_undo_note(
                        save_message_fn,
                        active_session_id,
                        active_history,
                        f"[undo] Deleted {result.path} "
                        "(it was created by an earlier write this session).",
                    )
                elif result.status == "already_gone":
                    cli_ui.print_warning(f"Already gone: {result.path}")
                    _save_undo_note(
                        save_message_fn,
                        active_session_id,
                        active_history,
                        f"[undo] {result.path} was already deleted; nothing to revert.",
                    )
                elif result.status in (
                    "refused_modified",
                    "refused_missing",
                    "refused_unsafe",
                ):
                    cli_ui.print_warning(
                        f"Not undoing {result.path} — {result.detail}."
                    )
                else:
                    cli_ui.print_error(f"Undo failed: {result.detail}")
            elif command.name == "/skills":
                cli_ui.print_skills(list_skills())
            elif command.name == "/skill":
                try:
                    _, rest = message.split(maxsplit=1)
                    skill_name, user_request = rest.split(maxsplit=1)
                except ValueError:
                    cli_ui.print_warning("Usage: /skill <name> <request>")
                    continue

                try:
                    message = build_skill_invocation_message(skill_name, user_request)
                except ValueError as exc:
                    cli_ui.print_warning(str(exc))
                    continue
            elif command.name == "/exit":
                cli_ui.print_success("Bye.")
                break
            else:
                continue

            if command.name not in ("/skill", "/retry"):
                continue
        else:
            resolved = resolve_skill_command(message)
            if resolved is not None:
                skill, user_request = resolved
                try:
                    message = build_skill_invocation_message(skill.name, user_request)
                    cli_ui.print_success(f"Loading skill: {skill.name}")
                except ValueError as exc:
                    cli_ui.print_warning(str(exc))
                    continue

        if hasattr(prompt, "prompt_async"):
            stdout_context = patch_stdout() if patch_stdout_enabled else nullcontext()
            with stdout_context:
                prompt_default = asyncio.run(
                    _run_turns_with_followups(
                        initial_message=message,
                        agent=agent,
                        active_session_id=active_session_id,
                        active_history=active_history,
                        prompt=prompt,
                        cli_ui=cli_ui,
                        pending_title_threads=pending_title_threads,
                        save_message_fn=save_message_fn,
                        rewrite_session_fn=rewrite_session_fn,
                        archive_session_fn=archive_session_fn,
                        load_session_meta_fn=load_session_meta_fn,
                        write_approval_state=write_approval_state,
                    )
                )
        else:
            _run_single_turn(
                message=message,
                agent=agent,
                active_session_id=active_session_id,
                active_history=active_history,
                prompt=prompt,
                cli_ui=cli_ui,
                pending_title_threads=pending_title_threads,
                save_message_fn=save_message_fn,
                rewrite_session_fn=rewrite_session_fn,
                archive_session_fn=archive_session_fn,
                load_session_meta_fn=load_session_meta_fn,
            )


def _execute_agent_turn(
    *,
    message,
    agent,
    active_session_id,
    active_history,
    prompt,
    cli_ui,
    input_reader=None,
):
    """Prepare and execute one agent turn; safe to run in a worker thread."""
    events = _build_agent_events(cli_ui)
    clarify_callback = _build_clarify_callback(
        cli_ui,
        prompt,
        input_reader=input_reader,
    )
    if isinstance(message, str):
        expanded_message = expand_context_references(
            message,
            current_session_id=active_session_id,
        )
        prepared_prompt = prepare_image_prompt(
            message,
            text_for_model=expanded_message,
            selector=clarify_callback,
        )
        for warning in prepared_prompt.warnings:
            cli_ui.print_warning(warning)
        user_content = prepared_prompt.content
        title_user_message = message
    else:
        user_content = message
        title_user_message = message_content_text(message)

    def _stream_writer(token: str) -> None:
        cli_ui.bump_tokens(max(1, len(token) // 4))
        cli_ui.stream_token(token)

    try:
        response, new_messages = agent.run_conversation(
            user_content,
            conversation_history=active_history,
            stream_writer=_stream_writer,
            events=events,
            clarify_callback=clarify_callback,
            current_session_id=active_session_id,
        )
    finally:
        cli_ui.stop_thinking()
    return response, new_messages, title_user_message


def _finish_agent_turn(
    *,
    response,
    new_messages,
    title_user_message,
    agent,
    active_session_id,
    active_history,
    cli_ui,
    pending_title_threads,
    save_message_fn,
    rewrite_session_fn,
    archive_session_fn,
    load_session_meta_fn,
) -> None:
    """Render and persist one completed turn on the REPL thread."""
    cli_ui.finish_assistant_response(response or "")

    compaction_outcome = getattr(agent, "last_compaction_outcome", None)
    replay_history = list(getattr(agent, "last_replay_history", []))
    if compaction_outcome is not None and compaction_outcome.did_compact:
        compacted_base_history = (
            replay_history[:-len(new_messages)] if new_messages else replay_history
        )
        archive_session_fn(active_session_id, reason="auto-compact")
        rewrite_session_fn(
            active_session_id,
            compacted_base_history,
            meta_updates=_build_compaction_meta_updates(
                load_session_meta_fn(active_session_id)
            ),
        )
        active_history[:] = compacted_base_history
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
        user_message=title_user_message,
        assistant_response=response or "",
        history=active_history,
    )
    if title_thread is not None:
        pending_title_threads.append(title_thread)


def _run_single_turn(
    *,
    message,
    agent,
    active_session_id,
    active_history,
    prompt,
    cli_ui,
    pending_title_threads,
    save_message_fn,
    rewrite_session_fn,
    archive_session_fn,
    load_session_meta_fn,
) -> None:
    """Compatibility path for injected prompt sessions without prompt_async."""
    cli_ui.set_render_markdown(_render_markdown_enabled(agent))
    cli_ui.begin_assistant_response()
    response, new_messages, title_user_message = _execute_agent_turn(
        message=message,
        agent=agent,
        active_session_id=active_session_id,
        active_history=active_history,
        prompt=prompt,
        cli_ui=cli_ui,
    )
    _finish_agent_turn(
        response=response,
        new_messages=new_messages,
        title_user_message=title_user_message,
        agent=agent,
        active_session_id=active_session_id,
        active_history=active_history,
        cli_ui=cli_ui,
        pending_title_threads=pending_title_threads,
        save_message_fn=save_message_fn,
        rewrite_session_fn=rewrite_session_fn,
        archive_session_fn=archive_session_fn,
        load_session_meta_fn=load_session_meta_fn,
    )


def _prompt_buffer_text(prompt: Any) -> str:
    buffer = getattr(prompt, "default_buffer", None)
    return str(getattr(buffer, "text", "") or "")


async def _cancel_prompt_task(task: Optional[asyncio.Task]) -> None:
    if task is None:
        return
    if not task.done():
        task.cancel()
    try:
        await task
    except (asyncio.CancelledError, KeyboardInterrupt, EOFError):
        pass


async def _run_turns_with_followups(
    *,
    initial_message,
    agent,
    active_session_id,
    active_history,
    prompt,
    cli_ui,
    pending_title_threads,
    save_message_fn,
    rewrite_session_fn,
    archive_session_fn,
    load_session_meta_fn,
    write_approval_state,
) -> str:
    """Run agent turns in a worker while the terminal queues follow-ups."""
    loop = asyncio.get_running_loop()
    broker = PromptBroker(loop)
    followups = FollowUpQueue()
    draft = ""

    if _confirm_edits_enabled(agent):
        set_write_approval_callback(
            _build_write_approval_callback(
                cli_ui,
                prompt,
                input_reader=broker.ask_from_worker,
                state=write_approval_state,
            )
        )

    current_message = initial_message
    try:
        while current_message is not None:
            cli_ui.set_render_markdown(_render_markdown_enabled(agent))
            cli_ui.begin_assistant_response()
            agent_task = asyncio.create_task(
                asyncio.to_thread(
                    _execute_agent_turn,
                    message=current_message,
                    agent=agent,
                    active_session_id=active_session_id,
                    active_history=active_history,
                    prompt=prompt,
                    cli_ui=cli_ui,
                    input_reader=broker.ask_from_worker,
                )
            )
            input_task: Optional[asyncio.Task] = asyncio.create_task(
                prompt.prompt_async(
                    [("class:prompt", "follow-up> ")],
                    default=draft,
                )
            )
            draft = ""
            modal_task: asyncio.Task = asyncio.create_task(broker.next_request())
            collect_input = True

            while True:
                wait_for = {agent_task, modal_task}
                if input_task is not None:
                    wait_for.add(input_task)
                done, _ = await asyncio.wait(
                    wait_for,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if input_task is not None and input_task in done:
                    try:
                        queued = input_task.result().strip()
                    except (KeyboardInterrupt, EOFError):
                        collect_input = False
                    else:
                        if queued.startswith("/"):
                            cli_ui.print_warning(
                                "Slash commands cannot be queued while Astra is working."
                            )
                        elif queued:
                            followups.put(queued)
                            cli_ui.print_success(
                                f"Queued follow-up ({followups.size()})."
                            )
                    input_task = None
                    if collect_input and agent_task not in done:
                        input_task = asyncio.create_task(
                            prompt.prompt_async(
                                [("class:prompt", "follow-up> ")]
                            )
                        )

                if modal_task in done:
                    request = modal_task.result()
                    if input_task is not None:
                        draft = _prompt_buffer_text(prompt)
                        await _cancel_prompt_task(input_task)
                        input_task = None
                    try:
                        answer = await prompt.prompt_async(request.message)
                    except (KeyboardInterrupt, EOFError):
                        answer = ""
                    if not request.result.done():
                        request.result.set_result(answer)
                    modal_task = asyncio.create_task(broker.next_request())
                    if collect_input and agent_task not in done:
                        input_task = asyncio.create_task(
                            prompt.prompt_async(
                                [("class:prompt", "follow-up> ")],
                                default=draft,
                            )
                        )
                        draft = ""
                    continue

                if agent_task in done:
                    if input_task is not None:
                        draft = _prompt_buffer_text(prompt)
                        await _cancel_prompt_task(input_task)
                    modal_task.cancel()
                    await _cancel_prompt_task(modal_task)
                    response, new_messages, title_user_message = agent_task.result()
                    _finish_agent_turn(
                        response=response,
                        new_messages=new_messages,
                        title_user_message=title_user_message,
                        agent=agent,
                        active_session_id=active_session_id,
                        active_history=active_history,
                        cli_ui=cli_ui,
                        pending_title_threads=pending_title_threads,
                        save_message_fn=save_message_fn,
                        rewrite_session_fn=rewrite_session_fn,
                        archive_session_fn=archive_session_fn,
                        load_session_meta_fn=load_session_meta_fn,
                    )
                    current_message = followups.pop()
                    if current_message is not None:
                        cli_ui.print_success("Running queued follow-up.")
                    break
    finally:
        broker.close()
        if _confirm_edits_enabled(agent):
            set_write_approval_callback(
                _build_write_approval_callback(
                    cli_ui,
                    prompt,
                    state=write_approval_state,
                )
            )
        else:
            set_write_approval_callback(None)
    return draft


def _render_markdown_enabled(agent) -> bool:
    config = getattr(agent, "config", {}) or {}
    cli_cfg = config.get("cli") or {}
    return bool(cli_cfg.get("render_markdown", False))


def _confirm_edits_enabled(agent) -> bool:
    config = getattr(agent, "config", {}) or {}
    cli_cfg = config.get("cli") or {}
    return bool(cli_cfg.get("confirm_edits", True))


def _build_write_approval_callback(
    cli_ui: CliUI,
    prompt_session: Any,
    *,
    input_reader: Optional[Callable[[Any], str]] = None,
    state: Optional[dict[str, bool]] = None,
) -> Callable[[str, str, str], bool]:
    """Return a callback that previews a diff and reads an apply/skip/always answer.

    "y" applies once, "n" rejects, "a" applies and stops asking for the rest of
    the session. The session-wide "always" latch lives in this closure so the
    tool side stays a simple bool.
    """
    approval_state = state if state is not None else {"always": False}
    read_input = input_reader or prompt_session.prompt

    def _approve(path: str, diff: str, action: str) -> bool:
        if approval_state["always"]:
            return True
        cli_ui.stop_thinking()
        cli_ui.print_diff(path, diff)
        try:
            answer = read_input(
                [("class:prompt", f"apply {action}? [y/n/a] ")]
            ).strip().lower()
        except (KeyboardInterrupt, EOFError):
            return False
        if answer == "a":
            approval_state["always"] = True
            return True
        return answer in ("y", "yes")

    return _approve


def _build_agent_events(cli_ui: CliUI) -> AgentEvents:
    """Wire a CliUI into the three agent hooks for spinner + tool feedback."""

    def on_thinking(active: bool) -> None:
        if active:
            cli_ui.start_thinking("thinking")
        else:
            cli_ui.pause_thinking()

    def on_tool_start(call_id: str, name: str, args: dict) -> None:
        preview = build_tool_preview(name, args)
        label = f"running {name}"
        if preview:
            label += f" {preview}"
        cli_ui.start_thinking(label)

    def on_tool_complete(call_id: str, name: str, args: dict, result: str) -> None:
        cli_ui.pause_thinking()
        cli_ui.bump_tool()
        cli_ui.set_heartbeat_label("thinking")
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
    *,
    input_reader: Optional[Callable[[Any], str]] = None,
) -> Callable[[str, Optional[List[str]]], str]:
    """Return a callback that renders the clarify prompt and reads one answer.

    Numeric input within range resolves to the matching choice text; anything
    else (including the implicit "Other" option) is returned verbatim.
    """

    read_input = input_reader or prompt_session.prompt

    def _clarify(question: str, choices: Optional[List[str]]) -> str:
        cli_ui.stop_thinking()
        cli_ui.print_clarify_question(question, choices)
        try:
            answer = read_input([("class:prompt", "answer> ")]).strip()
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

    model_config = getattr(agent, "model_config", None) or config.get("model", {})
    api_key = resolve_api_key(provider, model_config) or None

    user_msg_count = sum(1 for m in history if m.get("role") == "user")
    return maybe_auto_title(
        session_id,
        user_message,
        assistant_response,
        user_msg_count=user_msg_count,
        provider=provider,
        model=model,
        enabled=True,
        api_key=api_key,
    )


def _build_compaction_meta_updates(meta: dict) -> dict:
    timestamp = datetime.now().isoformat()
    return {
        "updated": timestamp,
        "compactions": int(meta.get("compactions", 0)) + 1,
        "last_compacted_at": timestamp,
    }
