"""Astra-Claw entry point.

Usage:
    astraclaw                                     # interactive mode (new session)
    astraclaw setup [provider|key|model]          # interactive setup wizard
    astraclaw --session <id>                      # resume a session
    astraclaw --sessions                          # list recent sessions
    astraclaw --workspace <path>                  # lock write_file to <path>
    astraclaw "read README.md"                    # one-shot mode (no session)
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  # Load .env file before anything reads env vars

from .agent.loop import AstraAgent
from .cli.context_refs import expand_context_references
from .cli.repl import run_interactive_repl
from .cli.ui import CliUI
from .constants import set_workspace_fence
from .llm import PROVIDER_KEY_ENV, resolve_api_key
from .session import create_session, load_session, list_sessions
from .tools.shell_tool import set_approval_callback


SETUP_SECTIONS = {"provider", "key", "model"}


def _apply_workspace_flag(argv: list) -> Path | None:
    """Consume --workspace <path> from argv, chdir, set the fence.

    Returns the resolved workspace Path, or None when the flag is absent.
    Exits the process when the flag is present but the path is invalid.
    """
    if "--workspace" not in argv:
        return None
    idx = argv.index("--workspace")
    if idx + 1 >= len(argv):
        print("Error: --workspace requires a path argument.")
        sys.exit(2)
    raw = argv[idx + 1]
    resolved = Path(raw).expanduser().resolve()
    if not resolved.exists() or not resolved.is_dir():
        print(f"Error: workspace path does not exist or is not a directory: {resolved}")
        sys.exit(2)
    os.chdir(resolved)
    set_workspace_fence(resolved)
    # Remove the flag + value so downstream arg parsing stays clean.
    del argv[idx : idx + 2]
    return resolved


def _ask_approval(command: str, reason: str) -> bool:
    """Prompt the user to approve a dangerous command."""
    print(f"\n  Warning: {reason}")
    print(f"  Command: {command}")
    try:
        answer = input("  Allow? [y/n]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        return False
    return answer in ("y", "yes")


def _cmd_setup(argv: list) -> int:
    """Run the setup wizard, optionally for a single section."""
    section = None
    if argv:
        candidate = argv[0]
        if candidate in SETUP_SECTIONS:
            section = candidate
        else:
            print(f"Unknown setup section: {candidate}")
            print(f"Available sections: {', '.join(sorted(SETUP_SECTIONS))}")
            return 2
    from .cli.setup import run_setup
    return run_setup(section=section)


def _has_usable_credentials() -> bool:
    """Return True when an API key is reachable for the configured provider."""
    try:
        from .config import load_user_config
    except Exception:
        return False
    user_cfg = load_user_config()
    model_cfg = user_cfg.get("model") if isinstance(user_cfg, dict) else None
    provider = (
        (model_cfg or {}).get("provider")
        if isinstance(model_cfg, dict)
        else None
    )
    if not provider:
        # No provider configured yet; check default env vars instead.
        return any(os.getenv(env) for env in PROVIDER_KEY_ENV.values())
    return bool(resolve_api_key(provider, model_cfg or {}))


def _prompt_first_run_setup() -> bool:
    """Ask the user whether to launch the setup wizard. Returns True if they did."""
    print()
    print("Astra-Claw isn't configured yet - no API key found.")
    print("  Run:  astraclaw setup")
    print()
    if not sys.stdin.isatty():
        print("Run 'astraclaw setup' from an interactive terminal to configure.")
        return False
    try:
        answer = input("Run setup now? [Y/n]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        return False
    if answer not in ("", "y", "yes"):
        print("You can run 'astraclaw setup' at any time to configure.")
        return False
    from .cli.setup import run_setup
    return run_setup() == 0


def main():
    # Register the approval callback so shell tool can ask the user
    set_approval_callback(_ask_approval)

    # Workspace fence flag must be handled first - it rewrites cwd and sys.argv.
    workspace = _apply_workspace_flag(sys.argv)

    # Subcommand: setup [section]
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        sys.exit(_cmd_setup(sys.argv[2:]))

    # --sessions flag: list recent sessions and exit
    if "--sessions" in sys.argv:
        CliUI().print_sessions(list_sessions())
        return

    is_one_shot = len(sys.argv) > 1 and "--session" not in sys.argv
    is_chat_mode = not is_one_shot

    # First-run guard: in chat mode, offer the setup wizard when no key is set.
    if is_chat_mode and not _has_usable_credentials():
        if not _prompt_first_run_setup():
            sys.exit(1)
        # Re-check after wizard run; bail out cleanly if still unconfigured.
        if not _has_usable_credentials():
            sys.exit(1)

    agent = AstraAgent()

    # One-shot mode: no session persistence
    if is_one_shot:
        message = " ".join(sys.argv[1:])
        message = expand_context_references(message)
        response, _ = agent.run_conversation(message)
        print(response)
        return

    # Resume existing session or create new one
    session_id = None
    history = []

    resumed = False
    if "--session" in sys.argv:
        idx = sys.argv.index("--session")
        if idx + 1 < len(sys.argv):
            session_id = sys.argv[idx + 1]
            history = load_session(session_id)
            if not history:
                print(f"Session '{session_id}' not found or empty.")
                return
            resumed = True

    if not session_id:
        session_id = create_session()

    run_interactive_repl(
        agent=agent,
        session_id=session_id,
        history=history,
        workspace=workspace,
        resumed=resumed,
    )


if __name__ == "__main__":
    main()
