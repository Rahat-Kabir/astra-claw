"""Smoke test the session-title auto-generator end-to-end.

Usage:
    # Synchronous mode - runs the LLM call on the main thread and prints the title.
    python scripts/smoke_title.py

    # Also persists to a fresh real session and prints the meta back.
    python scripts/smoke_title.py --persist

This bypasses the REPL so you can see any errors directly and don't race
against daemon-thread shutdown.
"""

import argparse
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

from astra_claw.agent.title_generator import (  # noqa: E402
    auto_title_session,
    generate_title,
)
from astra_claw.config import load_config  # noqa: E402
from astra_claw.llm import build_route  # noqa: E402
from astra_claw.session import (  # noqa: E402
    create_session,
    load_session_meta,
    save_message,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--persist", action="store_true", help="Also write to a real session.")
    parser.add_argument("--user", default="help me fix this python import error", help="User message.")
    parser.add_argument(
        "--assistant",
        default="Sure, let's check your sys.path and module layout.",
        help="Assistant reply.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logging.")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")

    config = load_config()
    route = build_route(config.get("model", {}), fallback=False)
    if not route:
        print("ERROR: no primary route resolved from config", file=sys.stderr)
        sys.exit(1)

    summary_model = (config.get("compression", {}) or {}).get("summary_model")
    provider = route["provider"]
    model = summary_model or route["model"]

    print(f"Provider: {provider}")
    print(f"Model:    {model}")
    print(f"User:     {args.user!r}")
    print(f"Reply:    {args.assistant!r}")
    print("---")

    title = generate_title(
        args.user,
        args.assistant,
        provider=provider,
        model=model,
    )
    if title is None:
        print("generate_title returned None (LLM call failed - rerun with --verbose).")
        sys.exit(2)

    print(f"Title:    {title!r}")

    if args.persist:
        session_id = create_session()
        save_message(session_id, {"role": "user", "content": args.user})
        save_message(session_id, {"role": "assistant", "content": args.assistant})
        auto_title_session(
            session_id,
            args.user,
            args.assistant,
            provider=provider,
            model=model,
        )
        meta = load_session_meta(session_id)
        print(f"Session:  {session_id}")
        print(f"Meta:     {meta}")


if __name__ == "__main__":
    main()
