"""Smoke test the delegate tool end-to-end against the real configured model.

Spawns a real child AstraAgent (no mocks), prints its live tool activity, then
shows the returned summary JSON and the persisted child session. Use this to
watch delegation actually work before trusting it from the REPL.

Usage:
    # Default: ask a child to read a repo file and report on it (exercises read_file).
    python scripts/smoke_delegate.py

    # Custom task:
    python scripts/smoke_delegate.py --goal "Count the .py files under astra_claw" \
        --context "Working directory is the repo root. Use the shell tool."

    # Pure-reasoning task (no tools, fast, works anywhere):
    python scripts/smoke_delegate.py --goal "Explain what a JSONL file is in 2 sentences." --context ""

    # Show the full child transcript that was saved to its session.
    python scripts/smoke_delegate.py --show-transcript

This bypasses the REPL so any errors surface directly.
"""

import argparse
import json
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

from astra_claw.agent.events import AgentEvents  # noqa: E402
from astra_claw.config import load_config  # noqa: E402
from astra_claw.llm import build_route  # noqa: E402
from astra_claw.session import load_session  # noqa: E402
from astra_claw.tools.delegate_tool import delegate_tool  # noqa: E402


def _make_events() -> AgentEvents:
    """Print the child's tool calls live so delegation isn't a black box."""

    def on_tool_start(call_id, name, args):
        primary = args.get("goal") or args.get("path") or args.get("command") or args.get("pattern") or ""
        primary = " ".join(str(primary).split())[:60]
        print(f"   child -> {name}  {primary}".rstrip())

    def on_tool_complete(call_id, name, args, result):
        flat = " ".join(str(result).split())[:70]
        print(f"   child <- {name}: {flat}")

    return AgentEvents(on_tool_start=on_tool_start, on_tool_complete=on_tool_complete)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--goal",
        default="Read the file pyproject.toml and report the project name and its CLI entry point.",
        help="The task for the child agent.",
    )
    parser.add_argument(
        "--context",
        default="The file pyproject.toml is in the current working directory (repo root).",
        help="Background passed to the child (file paths, constraints).",
    )
    parser.add_argument("--max-turns", type=int, default=None, help="Override the child's turn cap.")
    parser.add_argument("--show-transcript", action="store_true", help="Print the saved child transcript.")
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logging.")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")

    config = load_config()
    route = build_route(config.get("model", {}), fallback=False)
    if not route:
        print("ERROR: no primary route resolved from config", file=sys.stderr)
        sys.exit(1)

    print(f"Provider: {route['provider']}")
    print(f"Model:    {route['model']}")
    print(f"Goal:     {args.goal!r}")
    print(f"Context:  {args.context!r}")
    print("--- child running (live tool activity below) ---")

    raw = delegate_tool(
        goal=args.goal,
        context=args.context or None,
        max_turns=args.max_turns,
        parent_config=config,
        parent_session_id=None,
        events=_make_events(),
    )

    print("--- result ---")
    result = json.loads(raw)
    print(f"status:       {result.get('status')}")
    print(f"exit_reason:  {result.get('exit_reason')}")
    print(f"turns:        {result.get('turns')}")
    print(f"duration:     {result.get('duration_seconds')}s")
    if result.get("error"):
        print(f"error:        {result['error']}")
    print(f"child session: {result.get('child_session_id')}")
    print("\nsummary:")
    print(result.get("summary") or "(none)")

    if result.get("status") == "error":
        sys.exit(2)

    if args.show_transcript and result.get("child_session_id"):
        print("\n--- child transcript ---")
        for msg in load_session(result["child_session_id"]):
            role = msg.get("role")
            if msg.get("tool_calls"):
                names = [tc.get("function", {}).get("name", "?") for tc in msg["tool_calls"]]
                print(f"[{role}] tool_calls: {', '.join(names)}")
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                print(f"[{role}] {' '.join(content.split())[:200]}")


if __name__ == "__main__":
    main()
