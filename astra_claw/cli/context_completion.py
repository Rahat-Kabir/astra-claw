"""Prompt completions for inline context references."""

from __future__ import annotations

import re
from pathlib import Path

from prompt_toolkit.completion import Completer, Completion

from ..session import list_sessions
from ..tools.path_safety import inside_workspace_fence, is_sensitive_path


_REF_TOKEN_PATTERN = re.compile(r"(?<![\w@])@(file:[^\s]*|folder:[^\s]*|session:[^\s]*|diff)?$")
_SKIP_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".pytest_cache",
    ".uv-cache",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
}


class ContextReferenceCompleter(Completer):
    """Complete `@file:`, `@folder:`, `@diff`, and `@session:` refs."""

    def get_completions(self, document, complete_event):
        token = _current_ref_token(document.text_before_cursor)
        if token is None:
            return

        if token == "@":
            yield from _root_ref_completions()
            return

        if token == "@diff":
            yield Completion(
                "@diff",
                start_position=-len(token),
                display="@diff",
                display_meta="Attach unstaged git diff",
            )
            return

        if token.startswith("@file:"):
            partial = token[len("@file:") :]
            yield from _path_completions(token, partial, folders_only=False)
            return

        if token.startswith("@folder:"):
            partial = token[len("@folder:") :]
            yield from _path_completions(token, partial, folders_only=True)
            return

        if token.startswith("@session:"):
            partial = token[len("@session:") :]
            yield from _session_completions(token, partial)


def _current_ref_token(text_before_cursor: str) -> str | None:
    match = _REF_TOKEN_PATTERN.search(text_before_cursor)
    if match is None:
        return None
    return "@" + (match.group(1) or "")


def _root_ref_completions():
    refs = [
        ("@file:", "Attach file contents"),
        ("@folder:", "Attach folder tree"),
        ("@diff", "Attach unstaged git diff"),
        ("@session:", "Attach past session"),
    ]
    for text, meta in refs:
        yield Completion(text, start_position=-1, display=text, display_meta=meta)


def _path_completions(token: str, partial: str, *, folders_only: bool):
    base_dir, typed_name = _split_partial_path(partial)
    if not base_dir.exists() or not base_dir.is_dir():
        return

    prefix = "@folder:" if folders_only else "@file:"
    try:
        children = sorted(base_dir.iterdir(), key=lambda child: (not child.is_dir(), child.name.lower()))
    except OSError:
        return

    for child in children:
        if not _should_show_path(child, typed_name, folders_only=folders_only):
            continue
        completed_path = _join_completion_path(partial, child)
        if child.is_dir():
            completed_path += "/"
        completion_text = prefix + completed_path
        yield Completion(
            completion_text,
            start_position=-len(token),
            display=completion_text,
            display_meta="folder" if child.is_dir() else "file",
        )


def _split_partial_path(partial: str) -> tuple[Path, str]:
    normalized = partial.replace("\\", "/")
    if normalized.endswith("/"):
        return Path(partial).expanduser(), ""
    path = Path(partial).expanduser()
    parent = path.parent if str(path.parent) != "." else Path.cwd()
    return parent, path.name


def _join_completion_path(partial: str, child: Path) -> str:
    normalized = partial.replace("\\", "/")
    if normalized.endswith("/"):
        base = normalized
    elif "/" in normalized:
        base = normalized.rsplit("/", 1)[0] + "/"
    else:
        base = ""
    return base + child.name


def _should_show_path(child: Path, typed_name: str, *, folders_only: bool) -> bool:
    if child.name in _SKIP_NAMES:
        return False
    if child.name.startswith("."):
        return False
    if typed_name and not child.name.lower().startswith(typed_name.lower()):
        return False
    if folders_only and not child.is_dir():
        return False
    try:
        if not inside_workspace_fence(child):
            return False
        if is_sensitive_path(child):
            return False
    except OSError:
        return False
    return True


def _session_completions(token: str, partial: str):
    try:
        sessions = list_sessions()
    except Exception:
        return

    for session in sessions:
        session_id = str(session.get("id", ""))
        if not session_id:
            continue
        title = str(session.get("title", "") or "")
        if partial and not session_id.lower().startswith(partial.lower()):
            continue
        completion_text = f"@session:{session_id}"
        yield Completion(
            completion_text,
            start_position=-len(token),
            display=completion_text,
            display_meta=title or "session",
        )
