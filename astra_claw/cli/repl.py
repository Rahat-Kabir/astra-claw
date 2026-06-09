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
from ..config import save_user_config
from ..llm import format_route_label, resolve_api_key, validate_credentials
from ..session import (
    archive_session,
    create_session,
    list_sessions,
    load_session_meta,
    rewrite_session,
    save_message,
)
from ..tools.path_safety import set_write_approval_callback
from .commands import resolve_command, parse_model_arg, AstraCompleter
from .context_refs import expand_context_references
from .history_edit import truncate_for_retry
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

    if _confirm_edits_enabled(agent):
        set_write_approval_callback(_build_write_approval_callback(cli_ui, prompt))
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
        )
    finally:
        set_write_approval_callback(None)
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

        events = _build_agent_events(cli_ui)
        clarify_callback = _build_clarify_callback(cli_ui, prompt)
        expanded_message = expand_context_references(
            message,
            current_session_id=active_session_id,
        )

        cli_ui.set_render_markdown(_render_markdown_enabled(agent))
        cli_ui.begin_assistant_response()

        def _stream_writer(token: str) -> None:
            cli_ui.bump_tokens(max(1, len(token) // 4))
            cli_ui.stream_token(token)

        try:
            response, new_messages = agent.run_conversation(
                expanded_message,
                conversation_history=active_history,
                stream_writer=_stream_writer,
                events=events,
                clarify_callback=clarify_callback,
                current_session_id=active_session_id,
            )
        finally:
            cli_ui.stop_thinking()
        cli_ui.finish_assistant_response(response or "")

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
) -> Callable[[str, str, str], bool]:
    """Return a callback that previews a diff and reads an apply/skip/always answer.

    "y" applies once, "n" rejects, "a" applies and stops asking for the rest of
    the session. The session-wide "always" latch lives in this closure so the
    tool side stays a simple bool.
    """
    state = {"always": False}

    def _approve(path: str, diff: str, action: str) -> bool:
        if state["always"]:
            return True
        cli_ui.stop_thinking()
        cli_ui.print_diff(path, diff)
        try:
            answer = prompt_session.prompt(
                [("class:prompt", f"apply {action}? [y/n/a] ")]
            ).strip().lower()
        except (KeyboardInterrupt, EOFError):
            return False
        if answer == "a":
            state["always"] = True
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
