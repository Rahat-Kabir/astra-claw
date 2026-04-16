"""Agent event callbacks surface.

Optional hooks that the agent loop fires during a turn so the CLI/TUI can
show spinners, tool-call lines, or anything else without touching the loop.
All callbacks are optional; a missing callback is a no-op.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


@dataclass(frozen=True)
class AgentEvents:
    """Hooks fired by the agent during run_conversation.

    on_thinking(active):
        True right before a streamed LLM call starts,
        False on the first content/tool_call delta received.

    on_tool_start(call_id, name, args):
        Fired just before a tool is dispatched.

    on_tool_complete(call_id, name, args, result):
        Fired after the tool handler returns. `result` is the raw JSON string.
    """

    on_thinking: Optional[Callable[[bool], None]] = None
    on_tool_start: Optional[Callable[[str, str, Dict[str, Any]], None]] = None
    on_tool_complete: Optional[Callable[[str, str, Dict[str, Any], str], None]] = None
