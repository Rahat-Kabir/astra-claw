"""File tools — read_file, write_file."""

import json
from itertools import islice
from pathlib import Path

from .path_safety import (
    atomic_write_text,
    inside_workspace_fence,
    is_write_blocked,
    record_undo,
    request_write_approval,
    unified_diff,
)
from .registry import registry


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------

def read_file(args: dict) -> str:
    """Read a bounded page of lines, keeping text unchanged for patching."""
    path = args.get("path", "")
    if not path:
        return json.dumps({"error": "No path provided"})

    offset = args.get("offset", 1)
    limit = args.get("limit", 2000)
    if type(offset) is not int or offset < 1:
        return json.dumps({"error": "offset must be a positive integer (1-based)"})
    if type(limit) is not int or limit < 1:
        return json.dumps({"error": "limit must be a positive integer"})
    limit = min(limit, 2000)

    filepath = Path(path).expanduser()
    if not filepath.exists():
        return json.dumps({"error": f"File not found: {path}"})

    try:
        with filepath.open(encoding="utf-8") as stream:
            lines = list(islice(stream, offset - 1, offset - 1 + limit + 1))
        has_more = len(lines) > limit
        page = lines[:limit]
        return json.dumps({
            "path": str(filepath), "content": "".join(page),
            "offset": offset, "lines_read": len(page),
            "next_offset": offset + len(page) if has_more else None,
        })
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

    existed = filepath.exists() and filepath.is_file()
    old_content = ""
    if existed:
        try:
            old_content = filepath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            # Never treat an unreadable file as empty: the approval diff and
            # any later undo would silently destroy its real content.
            return json.dumps({"error": f"Cannot read existing file: {e}"})
    diff = unified_diff(old_content, content, str(filepath))

    if not request_write_approval(str(filepath), diff, "write"):
        return json.dumps(
            {"status": "rejected_by_user", "path": str(filepath)},
            ensure_ascii=False,
        )

    try:
        bytes_written = atomic_write_text(filepath, content)
    except Exception as e:
        return json.dumps({"error": f"Failed to write file: {e}"})
    record_undo(str(filepath), old_content, existed, content)
    return json.dumps({"path": str(filepath), "bytes_written": bytes_written})


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

READ_FILE_SCHEMA = {
    "name": "read_file",
    "description": "Read a text file in pages. offset is a 1-based line number; limit defaults to and is capped at 2000 lines. Follow next_offset to read more. Text has no added line-number prefixes, so it can be used directly with patch.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to read (absolute, relative, or ~/path)",
            },
            "offset": {
                "type": "integer", "minimum": 1,
                "description": "First line to read (1-based, default 1)",
            },
            "limit": {
                "type": "integer", "minimum": 1,
                "description": "Maximum lines to read (default and cap 2000)",
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
