"""Patch tool - targeted exact text replacement for existing files."""

import difflib
import json
from pathlib import Path

from .path_safety import atomic_write_text, inside_workspace_fence, is_write_blocked
from .registry import registry


def _unified_diff(old_content: str, new_content: str, path: str) -> str:
    """Return a unified diff for a file content change."""
    return "".join(
        difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def patch_file(args: dict) -> str:
    """Replace exact text in a file and return a JSON result."""
    path = args.get("path", "")
    old_text = args.get("old_text")
    new_text = args.get("new_text")
    replace_all = bool(args.get("replace_all", False))

    if not path:
        return json.dumps({"error": "No path provided"})
    if old_text is None or old_text == "":
        return json.dumps({"error": "old_text cannot be empty"})
    if new_text is None:
        return json.dumps({"error": "new_text is required"})

    filepath = Path(path).expanduser()

    if not inside_workspace_fence(filepath):
        return json.dumps({"error": f"Patch denied: '{path}' escapes workspace fence"})
    if is_write_blocked(filepath):
        return json.dumps({"error": f"Patch denied: '{path}' is a protected path"})
    if not filepath.exists():
        return json.dumps({"error": f"File not found: {path}"})
    if filepath.is_dir():
        return json.dumps({"error": f"Path is a directory: {path}"})

    try:
        old_content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        return json.dumps({"error": f"Failed to read file: {e}"})

    match_count = old_content.count(old_text)
    if match_count == 0:
        return json.dumps(
            {
                "error": "old_text not found",
                "hint": "Use read_file to inspect the current file content.",
            }
        )
    if match_count > 1 and not replace_all:
        return json.dumps(
            {
                "error": (
                    f"old_text matched {match_count} times. Provide more "
                    "surrounding context or set replace_all=true."
                )
            }
        )

    replacements = match_count if replace_all else 1
    new_content = old_content.replace(old_text, new_text, replacements)
    diff = _unified_diff(old_content, new_content, path)

    try:
        bytes_written = atomic_write_text(filepath, new_content)
    except Exception as e:
        return json.dumps({"error": f"Failed to write file: {e}"})

    return json.dumps(
        {
            "success": True,
            "path": str(filepath),
            "replacements": replacements,
            "bytes_written": bytes_written,
            "diff": diff,
        },
        ensure_ascii=False,
    )


PATCH_SCHEMA = {
    "name": "patch",
    "description": (
        "Edit an existing text file by replacing exact text. Use this for "
        "targeted edits instead of write_file. old_text must be unique unless "
        "replace_all is true. Returns a unified diff."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the existing text file to edit",
            },
            "old_text": {
                "type": "string",
                "description": (
                    "Exact text to replace. Include enough surrounding context "
                    "to make it unique."
                ),
            },
            "new_text": {
                "type": "string",
                "description": "Replacement text. Can be empty to delete matched text.",
            },
            "replace_all": {
                "type": "boolean",
                "description": (
                    "Replace all occurrences instead of requiring a unique match "
                    "(default: false)"
                ),
                "default": False,
            },
        },
        "required": ["path", "old_text", "new_text"],
    },
}


registry.register(
    name="patch",
    toolset="filesystem",
    schema=PATCH_SCHEMA,
    handler=patch_file,
)
