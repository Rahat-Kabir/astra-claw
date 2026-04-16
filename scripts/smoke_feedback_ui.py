"""Visual smoke test for the CLI feedback surface.

Renders one fake LLM turn through the real CliUI + AgentEvents wiring:
- Thinking spinner
- Tool call with preview and result summary
- Streamed text after the tool call

Run: python scripts/smoke_feedback_ui.py
"""

from __future__ import annotations

import json
import time

from astra_claw.cli.repl import _build_agent_events
from astra_claw.cli.ui import CliUI


def main() -> None:
    ui = CliUI()
    events = _build_agent_events(ui)

    ui.console.rule("[bold cyan]Astra-Claw feedback smoke test")

    events.on_thinking(True)
    time.sleep(0.8)
    events.on_thinking(False)

    events.on_tool_start("call_1", "read_file", {"path": "astra_claw/llm.py"})
    time.sleep(0.7)
    events.on_tool_complete(
        "call_1",
        "read_file",
        {"path": "astra_claw/llm.py"},
        json.dumps({"path": "astra_claw/llm.py", "content": "a\nb\nc\nd\ne"}),
    )

    events.on_thinking(True)
    time.sleep(0.5)
    events.on_tool_start(
        "call_2",
        "patch",
        {"path": "astra_claw/llm.py", "old_text": "...", "new_text": "..."},
    )
    time.sleep(0.7)
    events.on_tool_complete(
        "call_2",
        "patch",
        {"path": "astra_claw/llm.py"},
        json.dumps(
            {
                "success": True,
                "diff": "--- a/x\n+++ b/x\n-old\n-old2\n+new\n+new2\n+new3\n",
            }
        ),
    )

    events.on_thinking(True)
    time.sleep(0.4)
    events.on_tool_start("call_3", "shell", {"command": "pytest tests/ -q"})
    time.sleep(0.6)
    events.on_tool_complete(
        "call_3",
        "shell",
        {"command": "pytest tests/ -q"},
        json.dumps({"exit_code": 1, "output": "3 failed, 10 passed\n..."}),
    )

    events.on_thinking(True)
    time.sleep(0.4)
    events.on_tool_start("call_4", "search_files", {"pattern": "TODO"})
    time.sleep(0.5)
    events.on_tool_complete(
        "call_4",
        "search_files",
        {"pattern": "TODO"},
        json.dumps({"matches": ["a:1", "b:2", "c:3"], "total_count": 3}),
    )

    events.on_thinking(True)
    time.sleep(0.6)
    events.on_thinking(False)
    for token in ["Refactor ", "complete. ", "All ", "tests ", "pass."]:
        ui.stream_token(token)
        time.sleep(0.05)
    ui.newline()


if __name__ == "__main__":
    main()
