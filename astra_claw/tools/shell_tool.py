"""Shell tool — run terminal commands with dangerous command approval."""

import json
import re
import subprocess
from typing import Callable, Optional

from .registry import registry


# ---------------------------------------------------------------------------
# Dangerous command detection
# ---------------------------------------------------------------------------

DANGEROUS_PATTERNS = [
    (r"\brm\s+(-[^\s]*\s+)*/", "delete in root path"),
    (r"\brm\s+-[^\s]*r", "recursive delete"),
    (r"\bchmod\s+(-[^\s]*\s+)*(777|666)", "world-writable permissions"),
    (r"\bmkfs\b", "format filesystem"),
    (r"\bdd\s+.*if=", "disk copy"),
    (r"\bDROP\s+(TABLE|DATABASE)\b", "SQL DROP"),
    (r"\bDELETE\s+FROM\b(?!.*\bWHERE\b)", "SQL DELETE without WHERE"),
    (r"\bTRUNCATE\s+", "SQL TRUNCATE"),
    (r">\s*/etc/", "overwrite system config"),
    (r"\bkill\s+-9\s+-1\b", "kill all processes"),
    (r"\b(curl|wget)\b.*\|\s*(ba)?sh\b", "pipe remote content to shell"),
    (r"\bfind\b.*-delete\b", "find -delete"),
    (r"\bfind\b.*-exec\s+.*rm\b", "find -exec rm"),
]


def _detect_dangerous(command: str) -> Optional[str]:
    """Check if a command matches any dangerous pattern.

    Returns the reason string if dangerous, None if safe.
    """
    for pattern, reason in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return reason
    return None


# ---------------------------------------------------------------------------
# Approval callback (set by __main__.py)
# ---------------------------------------------------------------------------

_approval_callback: Optional[Callable[[str, str], bool]] = None


def set_approval_callback(callback: Callable[[str, str], bool]) -> None:
    """Register a callback for dangerous command approval.

    The callback receives (command, reason) and returns True to allow,
    False to deny. If no callback is set, dangerous commands are blocked.
    """
    global _approval_callback
    _approval_callback = callback


# ---------------------------------------------------------------------------
# Shell tool handler
# ---------------------------------------------------------------------------

def run_command(args: dict) -> str:
    """Execute a shell command and return stdout/stderr."""
    command = args.get("command", "")
    timeout = args.get("timeout", 30)

    if not command:
        return json.dumps({"error": "No command provided"})

    # Safety check
    danger_reason = _detect_dangerous(command)
    if danger_reason:
        if _approval_callback:
            allowed = _approval_callback(command, danger_reason)
            if not allowed:
                return json.dumps({"error": f"Command denied by user: {danger_reason}"})
        else:
            # No callback = no way to ask → block
            return json.dumps({"error": f"Blocked: {danger_reason}. Command: {command}"})

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        output = result.stdout
        if result.stderr:
            output = output + "\n[stderr]\n" + result.stderr if output else result.stderr

        return json.dumps({
            "output": output.strip(),
            "exit_code": result.returncode,
        })
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"Command timed out after {timeout} seconds"})
    except Exception as e:
        return json.dumps({"error": f"Failed to execute command: {e}"})


# ---------------------------------------------------------------------------
# Schema + register
# ---------------------------------------------------------------------------

SHELL_SCHEMA = {
    "name": "shell",
    "description": "Run a terminal command and return the output. Use this for listing files, running scripts, git commands, installing packages, or any shell operation. Returns stdout, stderr, and exit code.",
    "parameters": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute",
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds to wait (default: 30)",
                "default": 30,
            },
        },
        "required": ["command"],
    },
}

registry.register(name="shell", schema=SHELL_SCHEMA, handler=run_command)
