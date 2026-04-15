"""Interactive prompt loop for Astra-Claw."""

from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style

from ..constants import get_astraclaw_home
from ..session import create_session, list_sessions, save_message
from .commands import resolve_command, SlashCommandCompleter
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
    patch_stdout_enabled: bool = True,
) -> None:
    """Run the interactive CLI loop."""
    active_history = list(history) if history else []
    active_session_id = session_id
    prompt = prompt_session or build_prompt_session()
    cli_ui = ui or CliUI()

    cli_ui.print_banner(
        session_id=active_session_id,
        workspace=workspace,
        resumed=resumed,
        loaded_messages=len(active_history),
    )

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
            elif command.name == "/exit":
                cli_ui.print_success("Bye.")
                break
            continue

        response, new_messages = agent.run_conversation(
            message,
            conversation_history=active_history,
            stream_writer=cli_ui.stream_token,
        )
        if response:
            cli_ui.newline()

        for msg in new_messages:
            save_message_fn(active_session_id, msg)
        active_history.extend(new_messages)
