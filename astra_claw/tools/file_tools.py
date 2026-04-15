"""File tools — read_file, write_file."""

import json
from pathlib import Path

from .path_safety import atomic_write_text, inside_workspace_fence, is_write_blocked
from .registry import registry


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------

def read_file(args: dict) -> str:
    """Read a text file and return its content."""
    path = args.get("path", "")
    if not path:
        return json.dumps({"error": "No path provided"})

    filepath = Path(path).expanduser()
    if not filepath.exists():
        return json.dumps({"error": f"File not found: {path}"})

    try:
        content = filepath.read_text(encoding="utf-8")
        return json.dumps({"path": str(filepath), "content": content})
    except Exception as e:
        return json.dumps({"error": f"Failed to read file: {e}"})


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------

def write_file(args: dict) -> str:
    """Write content to a file, creating parent directories if needed."""
    path = args.get("path", "")
    content = args.get("content")

    if not path:
        return json.dumps({"error": "No path provided"})
    if content is None:
        return json.dumps({"error": "No content provided"})

    filepath = Path(path).expanduser()

    # Fence check — reject paths that escape the active workspace.
    if not inside_workspace_fence(filepath):
        return json.dumps({"error": f"Write denied: '{path}' escapes workspace fence"})

    # Safety check
    if is_write_blocked(filepath):
        return json.dumps({"error": f"Write denied: '{path}' is a protected path"})

    try:
        bytes_written = atomic_write_text(filepath, content)
        return json.dumps({"path": str(filepath), "bytes_written": bytes_written})
    except Exception as e:
        return json.dumps({"error": f"Failed to write file: {e}"})


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

READ_FILE_SCHEMA = {
    "name": "read_file",
    "description": "Read a text file and return its content. Use this to read any file on disk.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to read (absolute, relative, or ~/path)",
            },
        },
        "required": ["path"],
    },
}

WRITE_FILE_SCHEMA = {
    "name": "write_file",
    "description": "Write content to a file, completely replacing existing content. Creates parent directories automatically. OVERWRITES the entire file.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to write (will be created if it doesn't exist, overwritten if it does)",
            },
            "content": {
                "type": "string",
                "description": "Complete content to write to the file",
            },
        },
        "required": ["path", "content"],
    },
}

# ---------------------------------------------------------------------------
# Register tools
# ---------------------------------------------------------------------------

registry.register(
    name="read_file",
    toolset="filesystem",
    schema=READ_FILE_SCHEMA,
    handler=read_file,
)
registry.register(
    name="write_file",
    toolset="filesystem",
    schema=WRITE_FILE_SCHEMA,
    handler=write_file,
)
