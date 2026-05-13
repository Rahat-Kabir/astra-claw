"""Inline context reference expansion for CLI prompts.

Users can attach local context with refs like ``@file:README.md`` or
``@diff``. Expansion happens before the prompt reaches the agent.
"""

from __future__ import annotations

import mimetypes
import re
import subprocess
from pathlib import Path
from typing import Iterable, Optional

from ..constants import get_workspace_fence
from ..session import load_session
from ..tools.path_safety import inside_workspace_fence, is_sensitive_path


MAX_TOTAL_CONTEXT_CHARS = 24_000
MAX_FILE_CHARS = 12_000
MAX_FOLDER_ENTRIES = 200
MAX_DIFF_CHARS = 16_000
MAX_SESSION_CHARS = 16_000

_REF_PATTERN = re.compile(r"(?<![\w@])@(diff|file:[^\s]+|folder:[^\s]+|session:[^\s]+)")
_TRAILING_PUNCTUATION = ".,;!?)"
_SKIP_DIRS = {
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
_TEXT_EXTENSIONS = {
    ".bat",
    ".cfg",
    ".cmd",
    ".css",
    ".csv",
    ".env.example",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".lock",
    ".md",
    ".mjs",
    ".py",
    ".ps1",
    ".rst",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


def expand_context_references(
    message: str,
    *,
    current_session_id: Optional[str] = None,
    max_total_chars: int = MAX_TOTAL_CONTEXT_CHARS,
) -> str:
    """Append expanded ``@`` references to a user message.

    Invalid refs become warnings in the attached context block instead of
    raising exceptions, so normal chatting remains resilient.
    """
    refs = list(_iter_references(message))
    if not refs:
        return message

    blocks: list[str] = []
    used_chars = 0
    for ref in refs:
        block = _expand_reference(ref, current_session_id=current_session_id)
        if used_chars + len(block) > max_total_chars:
            remaining = max(0, max_total_chars - used_chars)
            if remaining > 200:
                blocks.append(_truncate_text(block, remaining, label=ref))
            blocks.append(
                f"## {ref}\n\n[WARNING: context reference budget exhausted; "
                "remaining references were not expanded.]"
            )
            break
        blocks.append(block)
        used_chars += len(block)

    if not blocks:
        return message
    return message.rstrip() + "\n\n--- Attached Context ---\n\n" + "\n\n".join(blocks)


def _iter_references(message: str) -> Iterable[str]:
    seen: set[str] = set()
    for match in _REF_PATTERN.finditer(message):
        ref = "@" + match.group(1).rstrip(_TRAILING_PUNCTUATION)
        if ref not in seen:
            seen.add(ref)
            yield ref


def _expand_reference(ref: str, *, current_session_id: Optional[str]) -> str:
    if ref == "@diff":
        return _expand_diff(ref)
    if ref.startswith("@file:"):
        return _expand_file(ref)
    if ref.startswith("@folder:"):
        return _expand_folder(ref)
    if ref.startswith("@session:"):
        return _expand_session(ref, current_session_id=current_session_id)
    return _warning_block(ref, "unsupported context reference")


def _expand_file(ref: str) -> str:
    raw = ref[len("@file:") :]
    raw_path, line_range = _split_file_ref(raw)
    path = Path(raw_path).expanduser()
    ok, error = _validate_read_path(path, must_be_file=True)
    if not ok:
        return _warning_block(ref, error)

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return _warning_block(ref, "binary or non-UTF-8 files are not supported")
    except OSError as exc:
        return _warning_block(ref, f"failed to read file: {exc}")

    if _looks_binary(path, content):
        return _warning_block(ref, "binary files are not supported")

    header = f"## {ref}\n\nPath: {_display_path(path)}"
    if line_range is not None:
        content = _slice_lines(content, line_range)
        header += f"\nLines: {line_range[0]}-{line_range[1]}"

    content = _truncate_text(content, MAX_FILE_CHARS, label=ref)
    return f"{header}\n\n```text\n{content}\n```"


def _expand_folder(ref: str) -> str:
    raw = ref[len("@folder:") :]
    path = Path(raw).expanduser()
    ok, error = _validate_read_path(path, must_be_file=False)
    if not ok:
        return _warning_block(ref, error)
    if not path.is_dir():
        return _warning_block(ref, "folder not found")

    lines: list[str] = []
    count = 0
    truncated = False
    root = path.resolve()
    for child in sorted(root.rglob("*"), key=lambda item: str(item).lower()):
        rel_parts = child.relative_to(root).parts
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        if count >= MAX_FOLDER_ENTRIES:
            truncated = True
            break
        marker = "/" if child.is_dir() else ""
        size = ""
        if child.is_file():
            try:
                size = f" ({child.stat().st_size} bytes)"
            except OSError:
                size = ""
        lines.append(f"- {child.relative_to(root).as_posix()}{marker}{size}")
        count += 1

    if truncated:
        lines.append("- ...")
    body = "\n".join(lines) if lines else "[empty folder]"
    return f"## {ref}\n\nPath: {_display_path(path)}\n\n```text\n{body}\n```"


def _expand_diff(ref: str) -> str:
    try:
        result = subprocess.run(
            ["git", "diff", "--no-ext-diff", "--", "."],
            cwd=get_workspace_fence(),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:
        return _warning_block(ref, f"failed to run git diff: {exc}")

    if result.returncode != 0:
        message = (result.stderr or result.stdout or "git diff failed").strip()
        return _warning_block(ref, message)
    diff = result.stdout.strip() or "[no unstaged git diff]"
    diff = _truncate_text(diff, MAX_DIFF_CHARS, label=ref)
    return f"## {ref}\n\n```diff\n{diff}\n```"


def _expand_session(ref: str, *, current_session_id: Optional[str]) -> str:
    session_id = ref[len("@session:") :].strip()
    if not session_id:
        return _warning_block(ref, "missing session id")
    if current_session_id and session_id == current_session_id:
        return _warning_block(ref, "current session cannot be attached to itself")

    messages = load_session(session_id)
    if not messages:
        return _warning_block(ref, "session not found or empty")

    lines: list[str] = []
    for message in messages:
        role = str(message.get("role", "unknown"))
        content = message.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        lines.append(f"{role.upper()}:\n{content.strip()}")

    body = _truncate_text("\n\n".join(lines), MAX_SESSION_CHARS, label=ref)
    return f"## {ref}\n\n```text\n{body}\n```"


def _split_file_ref(raw: str) -> tuple[str, Optional[tuple[int, int]]]:
    match = re.search(r":(\d+)(?:-(\d+))?$", raw)
    if match is None:
        return raw, None

    start = int(match.group(1))
    end = int(match.group(2) or start)
    if start < 1 or end < start:
        return raw[: match.start()], None
    return raw[: match.start()], (start, end)


def _slice_lines(content: str, line_range: tuple[int, int]) -> str:
    start, end = line_range
    lines = content.splitlines()
    if start > len(lines):
        return ""
    return "\n".join(lines[start - 1 : end])


def _validate_read_path(path: Path, *, must_be_file: bool) -> tuple[bool, str]:
    try:
        resolved = path.resolve()
    except OSError as exc:
        return False, f"invalid path: {exc}"

    if not inside_workspace_fence(resolved):
        return False, "path is outside the workspace fence"
    if is_sensitive_path(resolved):
        return False, "path is a sensitive or protected path"
    if not resolved.exists():
        return False, "file not found" if must_be_file else "folder not found"
    if must_be_file and not resolved.is_file():
        return False, "file not found"
    return True, ""


def _looks_binary(path: Path, content: str) -> bool:
    if "\x00" in content:
        return True
    suffix = path.suffix.lower()
    if suffix in _TEXT_EXTENSIONS or path.name.lower() == ".env.example":
        return False
    mime, _ = mimetypes.guess_type(str(path))
    return bool(mime and not mime.startswith("text/"))


def _truncate_text(text: str, limit: int, *, label: str) -> str:
    if len(text) <= limit:
        return text
    marker = f"\n[...truncated {label}: kept {limit} of {len(text)} chars...]\n"
    keep = max(0, limit - len(marker))
    return text[:keep].rstrip() + marker


def _warning_block(ref: str, message: str) -> str:
    return f"## {ref}\n\n[WARNING: {message}]"


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)
