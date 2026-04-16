import json
import os
from pathlib import Path
from unittest.mock import patch

from astra_claw.session import (
    archive_session,
    create_session,
    list_sessions,
    load_session,
    load_session_meta,
    rewrite_session,
    save_message,
)


class TestSession:
    def test_create_session_writes_meta_line(self, tmp_path):
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            session_id = create_session()

            path = tmp_path / "sessions" / f"{session_id}.jsonl"
            assert path.exists()

            first_line = path.read_text(encoding="utf-8").splitlines()[0]
            meta = json.loads(first_line)

            assert meta["type"] == "meta"
            assert meta["id"] == session_id
            assert "created" in meta

    def test_save_message_appends_timestamp(self, tmp_path):
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            session_id = create_session()
            save_message(session_id, {"role": "user", "content": "Hello"})

            path = tmp_path / "sessions" / f"{session_id}.jsonl"
            lines = path.read_text(encoding="utf-8").splitlines()

            assert len(lines) == 2
            entry = json.loads(lines[1])
            assert entry["role"] == "user"
            assert entry["content"] == "Hello"
            assert "ts" in entry

    def test_load_session_skips_meta_and_strips_ts(self, tmp_path):
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            session_id = create_session()
            save_message(session_id, {"role": "user", "content": "Hello"})
            save_message(session_id, {"role": "assistant", "content": "Hi"})

            messages = load_session(session_id)

            assert len(messages) == 2
            assert messages[0] == {"role": "user", "content": "Hello"}
            assert messages[1] == {"role": "assistant", "content": "Hi"}

    def test_load_session_missing_file_returns_empty_list(self, tmp_path):
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            assert load_session("missing_session") == []

    def test_load_session_skips_corrupt_json_lines(self, tmp_path):
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            session_id = create_session()
            path = tmp_path / "sessions" / f"{session_id}.jsonl"

            with open(path, "a", encoding="utf-8") as f:
                f.write('{"role": "user", "content": "ok", "ts": "123"}\n')
                f.write("{this is not json}\n")
                f.write('{"role": "assistant", "content": "fine", "ts": "456"}\n')

            messages = load_session(session_id)

            assert messages == [
                {"role": "user", "content": "ok"},
                {"role": "assistant", "content": "fine"},
            ]

    def test_list_sessions_returns_newest_first(self, tmp_path):
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            sessions_dir = tmp_path / "sessions"
            sessions_dir.mkdir(parents=True, exist_ok=True)

            older = sessions_dir / "older.jsonl"
            newer = sessions_dir / "newer.jsonl"

            older.write_text(
                json.dumps(
                    {
                        "type": "meta",
                        "id": "older",
                        "created": "2026-04-10T10:00:00",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            newer.write_text(
                json.dumps(
                    {
                        "type": "meta",
                        "id": "newer",
                        "created": "2026-04-11T10:00:00",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            sessions = list_sessions()

            assert [s["id"] for s in sessions[:2]] == ["newer", "older"]

    def test_list_sessions_skips_invalid_meta_files(self, tmp_path):
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            sessions_dir = tmp_path / "sessions"
            sessions_dir.mkdir(parents=True, exist_ok=True)

            good = sessions_dir / "good.jsonl"
            bad = sessions_dir / "bad.jsonl"

            good.write_text(
                json.dumps(
                    {
                        "type": "meta",
                        "id": "good",
                        "created": "2026-04-11T10:00:00",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            bad.write_text("not-json\n", encoding="utf-8")

            sessions = list_sessions()

            assert [s["id"] for s in sessions] == ["good"]

    def test_load_session_meta_reads_only_first_line(self, tmp_path):
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            session_id = create_session()
            save_message(session_id, {"role": "user", "content": "Hello"})

            meta = load_session_meta(session_id)

            assert meta["type"] == "meta"
            assert meta["id"] == session_id

    def test_archive_session_copies_existing_jsonl(self, tmp_path):
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            session_id = create_session()
            save_message(session_id, {"role": "user", "content": "Hello"})

            archive_path = archive_session(session_id, reason="compact")

            assert archive_path.exists()
            original = tmp_path / "sessions" / f"{session_id}.jsonl"
            assert archive_path.read_text(encoding="utf-8") == original.read_text(encoding="utf-8")

    def test_rewrite_session_replaces_messages_and_preserves_meta(self, tmp_path):
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            session_id = create_session()
            save_message(session_id, {"role": "user", "content": "Hello"})
            save_message(session_id, {"role": "assistant", "content": "Hi"})

            rewrite_session(
                session_id,
                [{"role": "assistant", "content": "[CONTEXT COMPACTION]\nsummary"}],
            )

            path = Path(tmp_path) / "sessions" / f"{session_id}.jsonl"
            lines = path.read_text(encoding="utf-8").splitlines()
            meta = json.loads(lines[0])
            rewritten = json.loads(lines[1])

            assert meta["type"] == "meta"
            assert meta["id"] == session_id
            assert rewritten == {"role": "assistant", "content": "[CONTEXT COMPACTION]\nsummary"}

    def test_rewrite_session_applies_meta_updates(self, tmp_path):
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            session_id = create_session()

            rewrite_session(
                session_id,
                [{"role": "assistant", "content": "summary"}],
                meta_updates={"compactions": 1, "last_compacted_at": "2026-04-16T00:00:00"},
            )

            meta = load_session_meta(session_id)

            assert meta["compactions"] == 1
            assert meta["last_compacted_at"] == "2026-04-16T00:00:00"
