"""Session persistence for Astra-Claw.

Stores conversation history as JSONL files in ~/.astraclaw/sessions/.
Each file = one session. Each line = one JSON message dict.
First line is always a metadata entry (type: "meta").
"""

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .constants import get_astraclaw_home


def _sessions_dir() -> Path:
    """Return the sessions directory, creating it if needed."""
    d = get_astraclaw_home() / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_session() -> str:
    """Create a new session and return its ID.

    ID format: 2026-04-10_a1b2c3d4 (date + 8-char hex).
    Writes a metadata line as the first entry in the JSONL file.
    """
    date_str = datetime.now().strftime("%Y-%m-%d")
    short_hex = uuid.uuid4().hex[:8]
    session_id = f"{date_str}_{short_hex}"

    meta = {
        "type": "meta",
        "id": session_id,
        "created": datetime.now().isoformat(),
    }

    path = _sessions_dir() / f"{session_id}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")

    return session_id


def load_session_meta(session_id: str) -> Dict[str, Any]:
    """Load only the metadata line for a session."""
    path = _sessions_dir() / f"{session_id}.jsonl"
    if not path.exists():
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
    except OSError:
        return {}

    if not first_line:
        return {}

    try:
        meta = json.loads(first_line)
    except json.JSONDecodeError:
        return {}

    return meta if meta.get("type") == "meta" else {}


def save_message(session_id: str, message: Dict) -> None:
    """Append a single message to a session's JSONL file.

    Adds a timestamp automatically. Works for user, assistant, and tool messages.
    """
    entry = {**message, "ts": datetime.now().isoformat()}

    path = _sessions_dir() / f"{session_id}.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def archive_session(session_id: str, *, reason: str) -> Path:
    """Copy the current session file into the archive directory."""
    source = _sessions_dir() / f"{session_id}.jsonl"
    if not source.exists():
        raise FileNotFoundError(f"Session not found: {session_id}")

    archive_dir = _sessions_dir() / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    archive_path = archive_dir / f"{session_id}.{timestamp}.{reason}.jsonl"
    shutil.copy2(source, archive_path)
    return archive_path


def rewrite_session(
    session_id: str,
    messages: List[Dict[str, Any]],
    *,
    meta_updates: Optional[Dict[str, Any]] = None,
) -> None:
    """Rewrite a session atomically with preserved metadata."""
    path = _sessions_dir() / f"{session_id}.jsonl"
    meta = load_session_meta(session_id) or {
        "type": "meta",
        "id": session_id,
        "created": datetime.now().isoformat(),
    }
    meta["type"] = "meta"
    meta["id"] = session_id
    if meta_updates:
        meta.update(meta_updates)

    temp_path = path.with_suffix(".jsonl.tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for message in messages:
            f.write(json.dumps(message, ensure_ascii=False) + "\n")
    temp_path.replace(path)


def get_session_title(session_id: str) -> Optional[str]:
    """Return the session's title if one has been set, else None."""
    title = load_session_meta(session_id).get("title")
    if isinstance(title, str) and title.strip():
        return title
    return None


def set_session_title(session_id: str, title: str) -> None:
    """Persist a title onto the session's meta line.

    Rewrites the JSONL atomically via rewrite_session. No-op if the session
    doesn't exist.
    """
    path = _sessions_dir() / f"{session_id}.jsonl"
    if not path.exists():
        return
    messages = load_session(session_id)
    rewrite_session(
        session_id,
        messages,
        meta_updates={
            "title": title,
            "titled_at": datetime.now().isoformat(),
        },
    )


def load_session(session_id: str) -> List[Dict]:
    """Load all messages from a session, skipping the meta line.

    Returns a list of message dicts ready to feed back into the agent.
    """
    path = _sessions_dir() / f"{session_id}.jsonl"
    if not path.exists():
        return []

    messages = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Skip meta lines
            if entry.get("type") == "meta":
                continue
            # Remove ts before feeding back to LLM (it doesn't need it)
            entry.pop("ts", None)
            messages.append(entry)

    return messages


def list_sessions() -> List[Dict]:
    """List all sessions, newest first.

    Reads the meta line from each JSONL file.
    Returns list of {"id": ..., "created": ...} dicts.
    """
    sessions = []
    sessions_dir = _sessions_dir()

    for path in sessions_dir.glob("*.jsonl"):
        try:
            meta = load_session_meta(path.stem)
            if meta.get("type") == "meta":
                sessions.append({
                    "id": meta.get("id", path.stem),
                    "created": meta.get("created", ""),
                    "title": meta.get("title", ""),
                })
        except OSError:
            continue

    sessions.sort(key=lambda s: s["created"], reverse=True)
    return sessions
