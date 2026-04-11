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
from typing import Callable, Dict, List

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Singleton registry that collects tool schemas + handlers from tool files."""

    def __init__(self):
        self._tools: Dict[str, dict] = {}

    def register(self, name: str, schema: dict, handler: Callable):
        """Register a tool. Called at module-import time by each tool file."""
        self._tools[name] = {"schema": schema, "handler": handler}

    def get_definitions(self) -> List[dict]:
        """Return OpenAI-format tool schemas for all registered tools."""
        return [
            {"type": "function", "function": entry["schema"]}
            for entry in self._tools.values()
        ]

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
