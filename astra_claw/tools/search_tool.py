"""Search tool — find files or search inside files, cross-platform."""

import json
import platform
import subprocess
from pathlib import Path

from .registry import registry


def _run(command: str, timeout: int = 30) -> str:
    """Run a shell command and return stdout."""
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return ""
    except Exception:
        return ""


def _search_content(pattern: str, path: str, file_glob: str = None) -> str:
    """Search inside files for a pattern (like grep)."""
    search_path = Path(path).expanduser()
    if not search_path.exists():
        return json.dumps({"error": f"Path not found: {path}"})

    is_windows = platform.system() == "Windows"

    if is_windows:
        # findstr: /S=recursive, /N=line numbers, /I=case-insensitive
        cmd = f'findstr /S /N /I "{pattern}" "{search_path}\\*"'
        if file_glob:
            cmd = f'findstr /S /N /I "{pattern}" "{search_path}\\{file_glob}"'
    else:
        # grep: -rn=recursive+line numbers, -i=case-insensitive
        cmd = f'grep -rn -i "{pattern}" "{search_path}"'
        if file_glob:
            cmd = f'grep -rn -i --include="{file_glob}" "{pattern}" "{search_path}"'

    output = _run(cmd, timeout=30)

    if not output:
        return json.dumps({"matches": [], "message": "No matches found"})

    # Parse results: limit to 50 lines to avoid overwhelming the LLM
    lines = output.split("\n")
    total = len(lines)
    lines = lines[:50]

    matches = []
    for line in lines:
        if not line:
            continue
        matches.append(line)

    result = {"matches": matches, "total_count": total}
    if total > 50:
        result["truncated"] = True
        result["message"] = f"Showing 50 of {total} matches"

    return json.dumps(result, ensure_ascii=False)


def _search_files(pattern: str, path: str) -> str:
    """Search for files by name pattern (like find)."""
    search_path = Path(path).expanduser()
    if not search_path.exists():
        return json.dumps({"error": f"Path not found: {path}"})

    is_windows = platform.system() == "Windows"

    if is_windows:
        cmd = f'dir /S /B "{search_path}\\{pattern}"'
    else:
        cmd = f'find "{search_path}" -type f -name "{pattern}"'

    output = _run(cmd, timeout=30)

    if not output:
        return json.dumps({"files": [], "message": "No files found"})

    files = [f for f in output.split("\n") if f]
    total = len(files)
    files = files[:50]

    result = {"files": files, "total_count": total}
    if total > 50:
        result["truncated"] = True

    return json.dumps(result, ensure_ascii=False)


def search_files(args: dict) -> str:
    """Search for files by name or search inside files for content."""
    pattern = args.get("pattern", "")
    if not pattern:
        return json.dumps({"error": "No pattern provided"})

    target = args.get("target", "content")
    path = args.get("path", ".")
    file_glob = args.get("file_glob")

    if target == "files":
        return _search_files(pattern, path)
    else:
        return _search_content(pattern, path, file_glob)


SEARCH_FILES_SCHEMA = {
    "name": "search_files",
    "description": (
        "Search file contents or find files by name. "
        "Use target='content' to search inside files (like grep). "
        "Use target='files' to find files by name pattern (like find). "
        "Use this instead of grep/findstr/find in shell — it works cross-platform."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Text or regex to search for (content mode), or glob pattern like '*.py' (files mode)",
            },
            "target": {
                "type": "string",
                "enum": ["content", "files"],
                "description": "'content' searches inside files, 'files' searches by filename (default: content)",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in (default: current directory)",
            },
            "file_glob": {
                "type": "string",
                "description": "Filter by file type, e.g. '*.py' (only for content search)",
            },
        },
        "required": ["pattern"],
    },
}

registry.register(name="search_files", schema=SEARCH_FILES_SCHEMA, handler=search_files)
