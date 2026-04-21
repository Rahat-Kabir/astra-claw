"""Session persistence for Astra-Claw.

Stores conversation history as JSONL files in ~/.astraclaw/sessions/.
Each file = one session. Each line = one JSON message dict.
First line is always a metadata entry (type: "meta").
"""

import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .constants import get_astraclaw_home


def _sessions_dir() -> Path:
    """Return the sessions directory, creating it if needed."""
    d = get_astraclaw_home() / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


_SEARCH_LIMIT_MAX = 5
_RECENT_LIMIT_DEFAULT = 8
_CANDIDATE_SCAN_LIMIT = 30
_RECENT_CANDIDATE_FALLBACK = 10
_SNIPPET_RADIUS = 60
_SNIPPET_MAX_LEN = 180
_PREVIEW_MAX_LEN = 180
_TITLE_EXACT_BOOST = 100
_BODY_EXACT_BOOST = 40
_TITLE_TERM_BOOST = 20
_BODY_TERM_BOOST = 10
_TOOL_TERM_BOOST = 3
_RECENCY_WINDOW_DAYS = 14


def _iter_session_paths() -> Iterable[Path]:
    return _sessions_dir().glob("*.jsonl")


def _normalize_search_text(text: str) -> str:
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return " ".join(text.split())


def _tokenize_query(query: str) -> tuple[str, List[str]]:
    normalized = _normalize_search_text(query)
    terms = [part for part in normalized.split(" ") if part]
    return normalized, terms


def _parse_role_filter(role_filter: Optional[str]) -> Optional[set[str]]:
    if not role_filter:
        return None
    allowed = {part.strip().lower() for part in role_filter.split(",") if part.strip()}
    return allowed or None


def _parse_created_at(created: Any) -> Optional[datetime]:
    if not isinstance(created, str) or not created.strip():
        return None
    try:
        return datetime.fromisoformat(created)
    except ValueError:
        return None


def _recency_bonus(created: Any) -> int:
    created_at = _parse_created_at(created)
    if created_at is None:
        return 0
    days_old = max(0, (datetime.now() - created_at).days)
    return max(0, _RECENCY_WINDOW_DAYS - days_old)


def _created_sort_key(created: Any) -> str:
    return created if isinstance(created, str) else ""


def _make_preview(messages: List[Dict[str, Any]]) -> str:
    for message in messages:
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return _truncate_preview(content)
    return ""


def _truncate_preview(text: str, limit: int = _PREVIEW_MAX_LEN) -> str:
    flat = " ".join(str(text).split())
    if len(flat) <= limit:
        return flat
    return flat[: max(limit - 3, 0)] + "..."


def _snippet_for_match(text: str, query_terms: List[str]) -> Optional[str]:
    if not isinstance(text, str) or not text.strip():
        return None

    lowered = text.lower()
    positions = [lowered.find(term.lower()) for term in query_terms if term]
    positions = [pos for pos in positions if pos >= 0]
    if not positions:
        return None

    start = max(0, min(positions) - _SNIPPET_RADIUS)
    end = min(len(text), min(positions) + _SNIPPET_RADIUS)
    snippet = text[start:end].strip()
    if len(snippet) > _SNIPPET_MAX_LEN:
        snippet = snippet[: _SNIPPET_MAX_LEN - 3].rstrip() + "..."
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return " ".join(snippet.split())


def _iter_session_messages(path: Path) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") == "meta":
                    continue
                entry.pop("ts", None)
                messages.append(entry)
    except OSError:
        return []
    return messages


def _score_title(meta: Dict[str, Any], normalized_query: str, query_terms: List[str]) -> int:
    title = meta.get("title")
    if not isinstance(title, str) or not title.strip():
        return 0

    normalized_title = _normalize_search_text(title)
    score = 0
    if normalized_query and normalized_query in normalized_title:
        score += _TITLE_EXACT_BOOST
    for term in query_terms:
        if term in normalized_title:
            score += _TITLE_TERM_BOOST
    return score


def _score_message(
    message: Dict[str, Any],
    *,
    normalized_query: str,
    query_terms: List[str],
    allowed_roles: Optional[set[str]],
) -> tuple[int, Optional[Dict[str, str]]]:
    role = str(message.get("role", "")).lower()
    if allowed_roles is not None and role not in allowed_roles:
        return 0, None

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        return 0, None

    normalized_content = _normalize_search_text(content)
    if not normalized_content:
        return 0, None

    score = 0
    if normalized_query and normalized_query in normalized_content:
        score += _BODY_EXACT_BOOST

    term_boost = _TOOL_TERM_BOOST if role == "tool" else _BODY_TERM_BOOST
    matched = False
    for term in query_terms:
        if term in normalized_content:
            score += term_boost
            matched = True

    if score <= 0 or not matched and _BODY_EXACT_BOOST != score:
        return score, None

    snippet = _snippet_for_match(content, query_terms)
    if snippet is None and normalized_query and normalized_query in normalized_content:
        snippet = _snippet_for_match(content, [normalized_query])
    if snippet is None:
        return score, None
    return score, {"role": role or "unknown", "text": snippet}


def _session_result(
    session_id: str,
    meta: Dict[str, Any],
    *,
    messages: List[Dict[str, Any]],
    score: int,
    snippets: List[Dict[str, str]],
) -> Dict[str, Any]:
    return {
        "session_id": session_id,
        "title": meta.get("title", ""),
        "created": meta.get("created", ""),
        "message_count": len(messages),
        "score": score,
        "preview": _make_preview(messages),
        "snippets": snippets,
    }


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
    for path in _iter_session_paths():
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


def list_recent_sessions(
    limit: int = _RECENT_LIMIT_DEFAULT,
    exclude_session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return recent session metadata for recall/browsing."""
    limit = max(1, min(int(limit or _RECENT_LIMIT_DEFAULT), _SEARCH_LIMIT_MAX))
    results: List[Dict[str, Any]] = []

    for session in list_sessions():
        session_id = session.get("id", "")
        if exclude_session_id and session_id == exclude_session_id:
            continue
        messages = _iter_session_messages(_sessions_dir() / f"{session_id}.jsonl")
        results.append({
            "session_id": session_id,
            "title": session.get("title", ""),
            "created": session.get("created", ""),
            "message_count": len(messages),
            "preview": _make_preview(messages),
        })
        if len(results) >= limit:
            break

    return {
        "success": True,
        "mode": "recent",
        "results": results,
        "count": len(results),
    }


def search_sessions(
    query: str,
    limit: int = 3,
    role_filter: Optional[str] = None,
    exclude_session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Search past JSONL sessions using a cheap two-pass rerank."""
    normalized_query, query_terms = _tokenize_query(query)
    limit = max(1, min(int(limit or 3), _SEARCH_LIMIT_MAX))
    allowed_roles = _parse_role_filter(role_filter)

    if not normalized_query:
        return list_recent_sessions(limit=limit, exclude_session_id=exclude_session_id)

    candidates: List[Dict[str, Any]] = []
    recent_fallback: List[Dict[str, Any]] = []
    for path in _iter_session_paths():
        session_id = path.stem
        if exclude_session_id and session_id == exclude_session_id:
            continue
        meta = load_session_meta(session_id)
        if meta.get("type") != "meta":
            continue
        title_score = _score_title(meta, normalized_query, query_terms)
        candidate = {
            "session_id": session_id,
            "meta": meta,
            "title_score": title_score,
            "recency_bonus": _recency_bonus(meta.get("created")),
            "created": _created_sort_key(meta.get("created")),
            "base_score": title_score + _recency_bonus(meta.get("created")),
        }
        candidates.append(candidate)
        recent_fallback.append(candidate)

    candidates.sort(key=lambda item: (item["base_score"], item["created"]), reverse=True)
    recent_fallback.sort(key=lambda item: item["created"], reverse=True)

    shortlisted: List[Dict[str, Any]] = []
    seen_session_ids: set[str] = set()
    for candidate in candidates[:_CANDIDATE_SCAN_LIMIT]:
        shortlisted.append(candidate)
        seen_session_ids.add(candidate["session_id"])
    for candidate in recent_fallback[:_RECENT_CANDIDATE_FALLBACK]:
        if candidate["session_id"] not in seen_session_ids:
            shortlisted.append(candidate)
            seen_session_ids.add(candidate["session_id"])

    results: List[Dict[str, Any]] = []
    for candidate in shortlisted:
        session_id = candidate["session_id"]
        meta = candidate["meta"]
        messages = _iter_session_messages(_sessions_dir() / f"{session_id}.jsonl")
        score = candidate["title_score"] + candidate["recency_bonus"]
        snippets: List[Dict[str, str]] = []
        for message in messages:
            message_score, snippet = _score_message(
                message,
                normalized_query=normalized_query,
                query_terms=query_terms,
                allowed_roles=allowed_roles,
            )
            score += message_score
            if snippet is not None and len(snippets) < 3:
                snippets.append(snippet)

        if score <= 0:
            continue
        if candidate["title_score"] <= 0 and not snippets:
            continue

        results.append(
            _session_result(
                session_id,
                meta,
                messages=messages,
                score=score,
                snippets=snippets,
            )
        )

    results.sort(key=lambda item: (item["score"], item["created"]), reverse=True)
    results = results[:limit]

    return {
        "success": True,
        "mode": "search",
        "query": query.strip(),
        "results": results,
        "count": len(results),
    }
