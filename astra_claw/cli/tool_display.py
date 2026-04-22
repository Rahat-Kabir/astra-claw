"""Pure display helpers for tool-call feedback in the CLI.

No Rich or prompt_toolkit imports -- just string formatting so these helpers
are easy to unit-test and reuse from any renderer.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


_PREVIEW_MAX = 60
_SUMMARY_MAX = 50


def _oneline(text: Any, limit: int = _PREVIEW_MAX) -> str:
    flat = " ".join(str(text).split())
    if len(flat) > limit:
        return flat[: max(limit - 3, 0)] + "..."
    return flat


def build_tool_preview(name: str, args: Dict[str, Any]) -> str:
    """Return a one-line summary of a tool call's primary argument."""
    if not isinstance(args, dict):
        return ""

    if name in ("read_file", "write_file", "patch"):
        return _oneline(args.get("path", ""))
    if name == "search_files":
        return _oneline(args.get("pattern") or args.get("name") or "")
    if name == "shell":
        return _oneline(args.get("command", ""))
    if name == "memory":
        action = args.get("action", "")
        target = args.get("target", "")
        return _oneline(f"{action} {target}".strip())
    if name == "todo":
        todos = args.get("todos")
        if todos is None:
            return "read"
        merge = args.get("merge", False)
        verb = "merge" if merge else "write"
        try:
            count = len(todos)
        except TypeError:
            count = 0
        return _oneline(f"{verb} {count} item{'s' if count != 1 else ''}")
    if name == "clarify":
        return _oneline(args.get("question", ""))
    if name == "session_search":
        query = args.get("query")
        return _oneline(query) if query else "recent sessions"
    if name == "web_extract":
        urls = args.get("urls")
        if isinstance(urls, list) and urls:
            first = str(urls[0])
            extra = len(urls) - 1
            if extra > 0:
                return _oneline(f"{first} (+{extra})")
            return _oneline(first)

    for key in ("path", "query", "command", "name", "prompt"):
        if key in args:
            return _oneline(args[key])
    return ""


def summarize_tool_result(name: str, result: str) -> Optional[str]:
    """Return a short, human-readable summary of a tool result, or None."""
    if not result:
        return None
    try:
        data = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return _oneline(result, _SUMMARY_MAX)

    if not isinstance(data, dict):
        return None

    err = data.get("error")
    if err:
        return f"error: {_oneline(err, _SUMMARY_MAX)}"

    if name == "read_file":
        content = data.get("content")
        if isinstance(content, str):
            return f"{len(content.splitlines())} lines"
        return None

    if name == "write_file":
        n = data.get("bytes_written")
        if isinstance(n, int):
            return f"wrote {_human_bytes(n)}"
        return None

    if name == "patch":
        diff = data.get("diff", "") or ""
        plus = 0
        minus = 0
        for line in diff.splitlines():
            if line.startswith("+++") or line.startswith("---"):
                continue
            if line.startswith("+"):
                plus += 1
            elif line.startswith("-"):
                minus += 1
        return f"+{plus} -{minus}"

    if name == "search_files":
        matches = data.get("matches") or []
        total = data.get("total_count", len(matches))
        return f"{total} match{'es' if total != 1 else ''}"

    if name == "shell":
        exit_code = data.get("exit_code", 0)
        output = data.get("output", "") or ""
        first_line = output.splitlines()[0] if output else ""
        if first_line:
            return f"exit {exit_code} - {_oneline(first_line, _SUMMARY_MAX)}"
        return f"exit {exit_code}"

    if name == "memory":
        if data.get("success"):
            return "ok"
        return None

    if name == "todo":
        summary = data.get("summary") or {}
        total = summary.get("total", 0)
        if not total:
            return "empty"
        parts = []
        for key in ("in_progress", "pending", "completed", "cancelled"):
            n = summary.get(key, 0)
            if n:
                parts.append(f"{n} {key.replace('_', ' ')}")
        return _oneline(" / ".join(parts) or f"{total} items", _SUMMARY_MAX)

    if name == "clarify":
        response = data.get("user_response")
        if isinstance(response, str) and response:
            return _oneline(response, _SUMMARY_MAX)
        return None

    if name == "session_search":
        total = data.get("count")
        if isinstance(total, int):
            return f"{total} session{'s' if total != 1 else ''}"
        return None

    if name in ("web_search", "web_extract"):
        results = data.get("results")
        if isinstance(results, list):
            total = len(results)
            noun = "result" if name == "web_search" else "page"
            if total == 1:
                return f"1 {noun}"
            return f"{total} {noun}s"
        return None

    return None


def _human_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"
