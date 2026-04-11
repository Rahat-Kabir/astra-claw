"""Session persistence for Astra-Claw.

Stores conversation history as JSONL files in ~/.astraclaw/sessions/.
Each file = one session. Each line = one JSON message dict.
First line is always a metadata entry (type: "meta").
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List

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


def save_message(session_id: str, message: Dict) -> None:
    """Append a single message to a session's JSONL file.

    Adds a timestamp automatically. Works for user, assistant, and tool messages.
    """
    entry = {**message, "ts": datetime.now().isoformat()}

    path = _sessions_dir() / f"{session_id}.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


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
            with open(path, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
            if not first_line:
                continue
            meta = json.loads(first_line)
            if meta.get("type") == "meta":
                sessions.append({
                    "id": meta.get("id", path.stem),
                    "created": meta.get("created", ""),
                })
        except (json.JSONDecodeError, OSError):
            continue

    sessions.sort(key=lambda s: s["created"], reverse=True)
    return sessions
