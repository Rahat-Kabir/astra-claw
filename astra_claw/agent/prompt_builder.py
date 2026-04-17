"""System prompt assembly for Astra-Claw.

MVP: hardcoded identity. Later: load from SOUL.md, inject memory, context files.
"""

import os
import platform

from .. import constants
from ..constants import get_workspace_fence
from ..soul import load_soul_md

DEFAULT_IDENTITY = """You are Astra-Claw, an AI agent that can take actions using tools.

When the user asks you to do something, use the tools available to you.
Do not describe what you would do -- actually do it by calling the appropriate tool.

Always respond concisely. If a tool returns an error, explain what went wrong.
"""

TOOL_POLICY = """Tool usage guidelines:
- Use read_file to inspect files
- Use patch for targeted edits to existing files
- Use write_file only for new files or deliberate full-file replacement
- Use shell for everything else: listing directories, running scripts, git commands, installing packages
- Use search_files for content grep and filename find across the tree
- Prefer dedicated file tools over shell for file read/write operations"""


MEMORY_HINT = (
    "You have persistent memory that survives across sessions. Save durable "
    "user preferences, corrections, and stable environment facts with the "
    "memory tool. Do not save temporary task progress or session outcomes."
)


def build_system_prompt(memory_store=None, include_memory_hint=None) -> str:
    """Assemble the system prompt. Layers will be added here over time."""
    parts = [(load_soul_md() or DEFAULT_IDENTITY).strip()]

    # Tool policy is a separate layer so persona (SOUL.md) can't drop it.
    parts.append(TOOL_POLICY)

    # Inject environment context so the LLM uses correct shell commands.
    cwd = os.getcwd()
    os_name = platform.system()  # "Windows", "Linux", "Darwin"
    if os_name == "Windows":
        shell_hint = (
            "Shell runs via Windows shell=True semantics (cmd-compatible). "
            "Use dir, type, where, findstr -- NOT ls, cat, grep."
        )
    else:
        shell_hint = "Shell is Unix. Use ls, cat, find, grep."

    parts.append(f"Environment: {os_name}, working directory: {cwd}")
    parts.append(shell_hint)

    # Workspace fence: only announce when explicitly set via --workspace.
    if constants._workspace_fence is not None:
        fence = get_workspace_fence()
        parts.append(
            f"Workspace fence: write_file and patch are jailed to {fence}. "
            "Do not attempt paths outside this directory."
        )

    # Auto-enable memory hint when a store is passed; explicit arg overrides.
    if include_memory_hint is None:
        include_memory_hint = memory_store is not None
    if include_memory_hint:
        parts.append(MEMORY_HINT)

    if memory_store is not None:
        user_block = memory_store.format_for_system_prompt("user")
        if user_block:
            parts.append(user_block)
        memory_block = memory_store.format_for_system_prompt("memory")
        if memory_block:
            parts.append(memory_block)

    return "\n\n".join(parts)
