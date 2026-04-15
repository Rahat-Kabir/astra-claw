"""Astra-Claw entry point.

Usage:
    python -m astra_claw                         # interactive mode (new session)
    python -m astra_claw --session <id>          # resume a session
    python -m astra_claw --sessions              # list recent sessions
    python -m astra_claw --workspace <path>      # lock write_file to <path>
    python -m astra_claw "read README.md"        # one-shot mode (no session)
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  # Load .env file before anything reads env vars

from .agent.loop import AstraAgent
from .cli.repl import run_interactive_repl
from .cli.ui import CliUI
from .constants import set_workspace_fence
from .session import create_session, load_session, list_sessions
from .tools.shell_tool import set_approval_callback


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


def main():
    # Register the approval callback so shell tool can ask the user
    set_approval_callback(_ask_approval)

    # Workspace fence flag must be handled first — it rewrites cwd and sys.argv.
    workspace = _apply_workspace_flag(sys.argv)

    # --sessions flag: list recent sessions and exit
    if "--sessions" in sys.argv:
        CliUI().print_sessions(list_sessions())
        return

    agent = AstraAgent()

    # One-shot mode: no session persistence
    if len(sys.argv) > 1 and "--session" not in sys.argv:
        message = " ".join(sys.argv[1:])
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
