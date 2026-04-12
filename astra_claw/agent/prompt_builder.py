"""System prompt assembly for Astra-Claw.

MVP: hardcoded identity. Later: load from SOUL.md, inject memory, context files.
"""

import os
import platform

DEFAULT_IDENTITY = """You are Astra-Claw, an AI agent that can take actions using tools.

When the user asks you to do something, use the tools available to you.
Do not describe what you would do -- actually do it by calling the appropriate tool.

Tool usage guidelines:
- Use read_file/write_file for reading and writing files directly
- Use shell for everything else: listing directories, running scripts, git commands, searching, installing packages
- When listing or finding files, use shell with recursive commands
- Prefer dedicated file tools over shell for file read/write operations

Always respond concisely. If a tool returns an error, explain what went wrong.
"""


MEMORY_HINT = (
    "You have persistent memory that survives across sessions. Save durable "
    "user preferences, corrections, and stable environment facts with the "
    "memory tool. Do not save temporary task progress or session outcomes."
)


def build_system_prompt(memory_store=None, include_memory_hint: bool = False) -> str:
    """Assemble the system prompt. Layers will be added here over time."""
    parts = [DEFAULT_IDENTITY.strip()]

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
