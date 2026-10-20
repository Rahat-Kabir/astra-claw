"""Bound model-visible tool text while retaining oversized output on disk."""

import json
import re
import time
from pathlib import Path
from uuid import uuid4

from ..constants import get_astraclaw_home
from ..tools.path_safety import atomic_write_text

MAX_LINES = 2000
MAX_BYTES = 50 * 1024
RETENTION_SECONDS = 7 * 24 * 60 * 60
_MAX_METADATA_BYTES = 4096
_ARTIFACT_NAME = re.compile(r"tool_[0-9a-f]{32}\.txt")


def _fits(text: str) -> bool:
    return len(text.encode("utf-8")) <= MAX_BYTES and len(text.splitlines()) <= MAX_LINES


def _preview(text: str) -> str:
    # Decode only whole UTF-8 characters; even a single huge line is bounded.
    prefix = text.encode("utf-8")[:MAX_BYTES].decode("utf-8", errors="ignore")
    return "".join(prefix.splitlines(keepends=True)[:MAX_LINES])


def _save_output(text: str) -> Path:
    directory = (get_astraclaw_home() / "tool-output").resolve()
    directory.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - RETENTION_SECONDS
    # Only remove our own expired artifacts, never arbitrary files or symlinks.
    for path in directory.iterdir():
        if not _ARTIFACT_NAME.fullmatch(path.name) or path.is_symlink() or not path.is_file():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except FileNotFoundError:
            pass  # Another run may have expired the same artifact.
    path = directory / f"tool_{uuid4().hex}.txt"
    atomic_write_text(path, text)
    return path


def bound_tool_result(result: str) -> str:
    """Keep small JSON results unchanged; bound large text before history/UI use.

    Preserve ordinary file/shell result fields when their non-text metadata is
    small. Other shapes become a preview of the complete JSON document. Never
    trust a tool's own `truncated` flag to bypass this shared limit.
    """
    data = json.loads(result)
    field = None
    if isinstance(data, dict):
        for candidate in ("output", "content", "summary"):
            if isinstance(data.get(candidate), str):
                metadata = {key: value for key, value in data.items() if key != candidate}
                if len(json.dumps(metadata, ensure_ascii=False).encode("utf-8")) <= _MAX_METADATA_BYTES:
                    field = candidate
                    break

    text = data[field] if field else json.dumps(data, ensure_ascii=False, indent=2)
    if _fits(text):
        return result

    path = _save_output(text)
    preview = _preview(text)
    marker = (
        f"[Output truncated; full output saved to {path}. "
        "Use read_file with offset (1-based) and limit to read it in sections. "
        "For a very long single line, use shell to inspect a character slice.]"
    )
    bounded = dict(data) if field else {}
    if not field and isinstance(data, dict):
        for key in ("exit_code", "status", "error"):
            value = data.get(key)
            if key not in data or not isinstance(value, (str, int, bool, type(None))):
                continue
            if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) <= 256:
                bounded[key] = value
    bounded[field or "output"] = preview
    bounded.update(truncated=True, output_path=str(path), truncation_message=marker)
    return json.dumps(bounded, ensure_ascii=False)
