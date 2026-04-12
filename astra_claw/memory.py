"""Persistent curated memory for Astra-Claw.

Two files under ~/.astraclaw/memory/:
  - MEMORY.md: agent notes (environment facts, project conventions, lessons learned)
  - USER.md:   user profile (preferences, communication style, habits)

Entries are delimited by the section sign (§) and stored as plain text.
Char-limited (not token-limited) so limits stay model-independent.

Frozen snapshot pattern:
  load_from_disk() captures _system_prompt_snapshot once. Mid-session writes
  update the live lists and disk, but NOT the snapshot. The system prompt
  stays stable for the whole session, preserving prefix cache. Snapshot
  refreshes on next session start.

Content scanning rejects prompt-injection / exfiltration payloads before
they can land in the system prompt.
"""

import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .constants import get_astraclaw_home


ENTRY_DELIMITER = "\n§\n"


def _memory_dir() -> Path:
    return get_astraclaw_home() / "memory"


_MEMORY_THREAT_PATTERNS = [
    (r"ignore\s+(previous|all|above|prior)\s+instructions", "prompt_injection"),
    (r"you\s+are\s+now\s+", "role_hijack"),
    (r"do\s+not\s+tell\s+the\s+user", "deception_hide"),
    (r"system\s+prompt\s+override", "sys_prompt_override"),
    (r"disregard\s+(your|all|any)\s+(instructions|rules|guidelines)", "disregard_rules"),
    (r"curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)", "exfil_curl"),
    (r"wget\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)", "exfil_wget"),
    (r"cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)", "read_secrets"),
    (r"authorized_keys", "ssh_backdoor"),
    (r"\$HOME/\.ssh|\~/\.ssh", "ssh_access"),
    (r"\$HOME/\.astraclaw/\.env|\~/\.astraclaw/\.env", "astraclaw_env"),
]

_INVISIBLE_CHARS = {
    "\u200b", "\u200c", "\u200d", "\u2060", "\ufeff",
    "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
}


def _scan_memory_content(content: str) -> Optional[str]:
    """Return an error string if content is unsafe to store, else None."""
    for char in _INVISIBLE_CHARS:
        if char in content:
            return (
                f"Blocked: content contains invisible unicode character "
                f"U+{ord(char):04X} (possible injection)."
            )
    for pattern, pid in _MEMORY_THREAT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return (
                f"Blocked: content matches threat pattern '{pid}'. Memory "
                f"entries are injected into the system prompt and must not "
                f"contain injection or exfiltration payloads."
            )
    return None


class MemoryStore:
    """Bounded, file-backed memory with frozen system-prompt snapshot."""

    def __init__(self, memory_char_limit: int = 2200, user_char_limit: int = 1375):
        self.memory_entries: List[str] = []
        self.user_entries: List[str] = []
        self.memory_char_limit = memory_char_limit
        self.user_char_limit = user_char_limit
        self._system_prompt_snapshot: Dict[str, str] = {"memory": "", "user": ""}

    def load_from_disk(self) -> None:
        _memory_dir().mkdir(parents=True, exist_ok=True)
        self.memory_entries = self._read_file(self._path_for("memory"))
        self.user_entries = self._read_file(self._path_for("user"))
        # Dedupe, preserve order
        self.memory_entries = list(dict.fromkeys(self.memory_entries))
        self.user_entries = list(dict.fromkeys(self.user_entries))
        self._system_prompt_snapshot = {
            "memory": self._render_block("memory", self.memory_entries),
            "user": self._render_block("user", self.user_entries),
        }

    def add(self, target: str, content: str) -> Dict[str, Any]:
        content = (content or "").strip()
        if not content:
            return {"success": False, "error": "Content cannot be empty."}

        scan_error = _scan_memory_content(content)
        if scan_error:
            return {"success": False, "error": scan_error}

        entries = self._entries_for(target)
        limit = self._char_limit(target)

        if content in entries:
            return self._success_response(target, "Entry already exists (no duplicate added).")

        new_entries = entries + [content]
        new_total = len(ENTRY_DELIMITER.join(new_entries))
        if new_total > limit:
            current = self._char_count(target)
            return {
                "success": False,
                "error": (
                    f"Memory at {current:,}/{limit:,} chars. Adding this entry "
                    f"({len(content)} chars) would exceed the limit. Replace "
                    f"or remove existing entries first."
                ),
                "usage": f"{current:,}/{limit:,}",
            }

        entries.append(content)
        self._set_entries(target, entries)
        self._write_file(self._path_for(target), entries)
        return self._success_response(target, "Entry added.")

    def replace(self, target: str, old_text: str, new_content: str) -> Dict[str, Any]:
        old_text = (old_text or "").strip()
        new_content = (new_content or "").strip()
        if not old_text:
            return {"success": False, "error": "old_text cannot be empty."}
        if not new_content:
            return {
                "success": False,
                "error": "new_content cannot be empty. Use 'remove' to delete entries.",
            }

        scan_error = _scan_memory_content(new_content)
        if scan_error:
            return {"success": False, "error": scan_error}

        entries = self._entries_for(target)
        matches = [(i, e) for i, e in enumerate(entries) if old_text in e]
        if not matches:
            return {"success": False, "error": f"No entry matched '{old_text}'."}
        if len(matches) > 1 and len({e for _, e in matches}) > 1:
            previews = [e[:80] + ("..." if len(e) > 80 else "") for _, e in matches]
            return {
                "success": False,
                "error": f"Multiple entries matched '{old_text}'. Be more specific.",
                "matches": previews,
            }

        idx = matches[0][0]
        limit = self._char_limit(target)
        test_entries = entries.copy()
        test_entries[idx] = new_content
        new_total = len(ENTRY_DELIMITER.join(test_entries))
        if new_total > limit:
            return {
                "success": False,
                "error": (
                    f"Replacement would put memory at {new_total:,}/{limit:,} chars. "
                    f"Shorten the new content or remove other entries first."
                ),
            }

        entries[idx] = new_content
        self._set_entries(target, entries)
        self._write_file(self._path_for(target), entries)
        return self._success_response(target, "Entry replaced.")

    def remove(self, target: str, old_text: str) -> Dict[str, Any]:
        old_text = (old_text or "").strip()
        if not old_text:
            return {"success": False, "error": "old_text cannot be empty."}

        entries = self._entries_for(target)
        matches = [(i, e) for i, e in enumerate(entries) if old_text in e]
        if not matches:
            return {"success": False, "error": f"No entry matched '{old_text}'."}
        if len(matches) > 1 and len({e for _, e in matches}) > 1:
            previews = [e[:80] + ("..." if len(e) > 80 else "") for _, e in matches]
            return {
                "success": False,
                "error": f"Multiple entries matched '{old_text}'. Be more specific.",
                "matches": previews,
            }

        idx = matches[0][0]
        entries.pop(idx)
        self._set_entries(target, entries)
        self._write_file(self._path_for(target), entries)
        return self._success_response(target, "Entry removed.")

    def format_for_system_prompt(self, target: str) -> Optional[str]:
        """Return the frozen snapshot block, or None if empty at load time."""
        block = self._system_prompt_snapshot.get(target, "")
        return block if block else None

    # -- internals --

    @staticmethod
    def _path_for(target: str) -> Path:
        if target == "user":
            return _memory_dir() / "USER.md"
        return _memory_dir() / "MEMORY.md"

    def _entries_for(self, target: str) -> List[str]:
        return self.user_entries if target == "user" else self.memory_entries

    def _set_entries(self, target: str, entries: List[str]) -> None:
        if target == "user":
            self.user_entries = entries
        else:
            self.memory_entries = entries

    def _char_limit(self, target: str) -> int:
        return self.user_char_limit if target == "user" else self.memory_char_limit

    def _char_count(self, target: str) -> int:
        entries = self._entries_for(target)
        return len(ENTRY_DELIMITER.join(entries)) if entries else 0

    def _success_response(self, target: str, message: Optional[str] = None) -> Dict[str, Any]:
        entries = self._entries_for(target)
        current = self._char_count(target)
        limit = self._char_limit(target)
        pct = min(100, int((current / limit) * 100)) if limit > 0 else 0
        resp: Dict[str, Any] = {
            "success": True,
            "target": target,
            "entries": entries,
            "usage": f"{pct}% — {current:,}/{limit:,} chars",
            "entry_count": len(entries),
        }
        if message:
            resp["message"] = message
        return resp

    def _render_block(self, target: str, entries: List[str]) -> str:
        if not entries:
            return ""
        limit = self._char_limit(target)
        content = ENTRY_DELIMITER.join(entries)
        current = len(content)
        pct = min(100, int((current / limit) * 100)) if limit > 0 else 0
        if target == "user":
            header = f"USER PROFILE (who the user is) [{pct}% — {current:,}/{limit:,} chars]"
        else:
            header = f"MEMORY (your personal notes) [{pct}% — {current:,}/{limit:,} chars]"
        separator = "=" * 46
        return f"{separator}\n{header}\n{separator}\n{content}"

    @staticmethod
    def _read_file(path: Path) -> List[str]:
        if not path.exists():
            return []
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return []
        if not raw.strip():
            return []
        entries = [e.strip() for e in raw.split(ENTRY_DELIMITER)]
        return [e for e in entries if e]

    @staticmethod
    def _write_file(path: Path, entries: List[str]) -> None:
        """Atomic write via temp-file + os.replace."""
        path.parent.mkdir(parents=True, exist_ok=True)
        content = ENTRY_DELIMITER.join(entries) if entries else ""
        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent), suffix=".tmp", prefix=".mem_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(path))
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
