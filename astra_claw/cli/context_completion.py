"""Prompt completions for inline context references."""

from __future__ import annotations

import os
import re
from pathlib import Path

from prompt_toolkit.completion import Completer, Completion

from ..constants import get_workspace_fence
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
_MAX_FUZZY_RESULTS = 25


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
    scope, query = _split_search_scope(partial)
    prefix = "@folder:" if folders_only else "@file:"

    if not query:
        if not scope.exists() or not scope.is_dir():
            return
        yield from _directory_completions(token, partial, scope, folders_only=folders_only, prefix=prefix)
        return

    for rel_path, path in _fuzzy_find_paths(scope, query, folders_only=folders_only):
        completion_path = rel_path + ("/" if path.is_dir() else "")
        completion_text = prefix + completion_path
        yield Completion(
            completion_text,
            start_position=-len(token),
            display=completion_text,
            display_meta=_path_display_meta(path),
        )


def _split_search_scope(partial: str) -> tuple[Path, str]:
    normalized = partial.replace("\\", "/")
    fence = get_workspace_fence()

    if normalized.endswith("/"):
        root = _resolve_scope_path(normalized, fence)
        return root, ""

    if "/" in normalized:
        dir_part, query = normalized.rsplit("/", 1)
        root = _resolve_scope_path(dir_part, fence)
        if root.exists() and root.is_dir():
            return root, query

    return fence, normalized


def _resolve_scope_path(path_text: str, fence: Path) -> Path:
    path = Path(path_text).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (fence / path).resolve()


def _directory_completions(
    token: str,
    partial: str,
    base_dir: Path,
    *,
    folders_only: bool,
    prefix: str,
):
    normalized = partial.replace("\\", "/")
    if normalized.endswith("/"):
        typed_name = ""
    else:
        typed_name = Path(partial).name if partial else ""

    try:
        children = sorted(base_dir.iterdir(), key=lambda child: (not child.is_dir(), child.name.lower()))
    except OSError:
        return

    for child in children:
        if not _should_show_path(child, typed_name, folders_only=folders_only):
            continue
        rel_path = _relative_ref_path(child, get_workspace_fence())
        if child.is_dir():
            rel_path += "/"
        completion_text = prefix + rel_path
        yield Completion(
            completion_text,
            start_position=-len(token),
            display=completion_text,
            display_meta=_path_display_meta(child),
        )


def _fuzzy_find_paths(scope: Path, query: str, *, folders_only: bool) -> list[tuple[str, Path]]:
    if not query.strip():
        return []

    fence = get_workspace_fence()
    try:
        if not scope.exists() or not inside_workspace_fence(scope):
            return []
    except OSError:
        return []

    matches: list[tuple[int, int, str, Path]] = []
    query_lower = query.lower()

    for path in _iter_candidates(scope, folders_only=folders_only):
        rel_path = _relative_ref_path(path, fence)
        score = _fuzzy_score(rel_path, path.name, query_lower)
        if score is None:
            continue
        matches.append((score, len(rel_path), rel_path, path))

    matches.sort(key=lambda item: (item[0], item[1], item[2].lower()))
    seen: set[str] = set()
    results: list[tuple[str, Path]] = []
    for _, _, rel_path, path in matches:
        if rel_path in seen:
            continue
        seen.add(rel_path)
        results.append((rel_path, path))
        if len(results) >= _MAX_FUZZY_RESULTS:
            break
    return results


def _iter_candidates(root: Path, *, folders_only: bool):
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        dirnames[:] = [
            name
            for name in dirnames
            if name not in _SKIP_NAMES and not name.startswith(".")
        ]

        if folders_only:
            names = dirnames
            is_dir = True
        else:
            names = filenames + dirnames
            is_dir = False

        for name in names:
            child = current / name
            child_is_dir = child.is_dir()
            if not folders_only and name in dirnames:
                child_is_dir = True
            if folders_only and not child_is_dir:
                continue
            if _path_allowed(child):
                yield child


def _fuzzy_score(rel_path: str, name: str, query: str) -> int | None:
    name_lower = name.lower()
    path_lower = rel_path.lower()

    if name_lower == query:
        return 0
    if name_lower.startswith(query):
        return 1
    if query in name_lower:
        return 2
    if query in path_lower:
        return 3

    tokens = [part for part in re.split(r"[\s_/\\.-]+", query) if part]
    if tokens and all(token in path_lower for token in tokens):
        return 4
    return None


def _relative_ref_path(path: Path, fence: Path) -> str:
    try:
        rel = path.resolve().relative_to(fence.resolve())
    except ValueError:
        rel = path
    return rel.as_posix()


def _path_display_meta(path: Path) -> str:
    if path.is_dir():
        try:
            count = sum(1 for child in path.iterdir() if not child.name.startswith("."))
            return f"folder · {count} items"
        except OSError:
            return "folder"
    try:
        size = path.stat().st_size
        if size < 1024:
            return f"file · {size} B"
        return f"file · {size / 1024:.1f} KB"
    except OSError:
        return "file"


def _should_show_path(child: Path, typed_name: str, *, folders_only: bool) -> bool:
    if child.name in _SKIP_NAMES:
        return False
    if child.name.startswith("."):
        return False
    if typed_name and not child.name.lower().startswith(typed_name.lower()):
        return False
    if folders_only and not child.is_dir():
        return False
    return _path_allowed(child)


def _path_allowed(path: Path) -> bool:
    try:
        if not inside_workspace_fence(path):
            return False
        if is_sensitive_path(path):
            return False
    except OSError:
        return False
    return True


def _session_completions(token: str, partial: str):
    try:
        sessions = list_sessions()
    except Exception:
        return

    partial_lower = partial.lower()
    ranked: list[tuple[int, str, str, str]] = []

    for session in sessions:
        session_id = str(session.get("id", ""))
        if not session_id:
            continue
        title = str(session.get("title", "") or "")
        score = _session_match_score(session_id, title, partial_lower)
        if score is None:
            continue
        ranked.append((score, session_id, title, f"@session:{session_id}"))

    ranked.sort(key=lambda item: (item[0], item[1]))
    for _, session_id, title, completion_text in ranked[:_MAX_FUZZY_RESULTS]:
        yield Completion(
            completion_text,
            start_position=-len(token),
            display=completion_text,
            display_meta=title or "session",
        )


def _session_match_score(session_id: str, title: str, partial_lower: str) -> int | None:
    if not partial_lower:
        return 0
    session_lower = session_id.lower()
    title_lower = title.lower()
    if session_lower.startswith(partial_lower):
        return 0
    if title_lower.startswith(partial_lower):
        return 1
    if partial_lower in session_lower:
        return 2
    if partial_lower in title_lower:
        return 3
    return None
