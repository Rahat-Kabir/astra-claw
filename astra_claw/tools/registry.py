"""Central registry for all Astra-Claw tools.

Each tool file calls registry.register() at module level to declare its
schema and handler. agent/loop.py queries the registry for schemas and
dispatches tool calls by name.

Import chain (circular-import safe):
    tools/registry.py  (no imports from agent or tool files)
           ^
    tools/*.py  (import from tools.registry at module level)
           ^
    agent/loop.py  (imports registry + all tool modules)
"""

import json
import logging
from typing import Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Singleton registry that collects tool schemas + handlers from tool files."""

    def __init__(self):
        self._tools: Dict[str, dict] = {}

    def register(
        self,
        name: str,
        toolset: str,
        schema: dict,
        handler: Callable,
        check_fn: Optional[Callable] = None,
    ):
        """Register a tool. Called at module-import time by each tool file."""
        self._tools[name] = {
            "toolset": toolset,
            "schema": schema,
            "handler": handler,
            "check_fn": check_fn,
        }

    def get_definitions(self, enabled_toolsets: Optional[Set[str]] = None) -> List[dict]:
        """Return OpenAI-format tool schemas for registered and available tools."""
        definitions = []
        for entry in self._tools.values():
            if enabled_toolsets is not None and entry["toolset"] not in enabled_toolsets:
                continue

            check_fn = entry.get("check_fn")
            if check_fn is not None:
                try:
                    if not check_fn():
                        continue
                except Exception as e:
                    logger.debug("Tool availability check failed: %s", e)
                    continue

            definitions.append({"type": "function", "function": entry["schema"]})

        return definitions

    def dispatch(self, name: str, args: dict) -> str:
        """Execute a tool handler by name. Returns a JSON string."""
        entry = self._tools.get(name)
        if not entry:
            return json.dumps({"error": f"Unknown tool: {name}"})
        try:
            return entry["handler"](args)
        except Exception as e:
            logger.exception("Tool %s dispatch error: %s", name, e)
            return json.dumps({"error": f"Tool execution failed: {type(e).__name__}: {e}"})


# Singleton — every tool file imports this instance
registry = ToolRegistry()
