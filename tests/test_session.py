import json
import os
from pathlib import Path
from unittest.mock import patch

from astra_claw.session import (
    archive_session,
    create_session,
    get_session_title,
    list_recent_sessions,
    list_sessions,
    load_session,
    load_session_meta,
    rewrite_session,
    save_message,
    search_sessions,
    set_session_title,
)


def _write_session_file(
    root: Path,
    *,
    session_id: str,
    created: str,
    title: str = "",
    messages: list[dict] | None = None,
    bad_lines: list[str] | None = None,
):
    sessions_dir = root / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = sessions_dir / f"{session_id}.jsonl"
    meta = {"type": "meta", "id": session_id, "created": created}
    if title:
        meta["title"] = title

    lines = [json.dumps(meta, ensure_ascii=False)]
    for message in messages or []:
        entry = {**message, "ts": "2026-04-21T00:00:00"}
        lines.append(json.dumps(entry, ensure_ascii=False))
    for bad_line in bad_lines or []:
        lines.append(bad_line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


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

    def test_get_session_title_returns_none_when_unset(self, tmp_path):
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            session_id = create_session()
            assert get_session_title(session_id) is None

    def test_set_session_title_round_trip(self, tmp_path):
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            session_id = create_session()
            save_message(session_id, {"role": "user", "content": "Hello"})
            save_message(session_id, {"role": "assistant", "content": "Hi"})

            set_session_title(session_id, "Greeting The User")

            assert get_session_title(session_id) == "Greeting The User"
            meta = load_session_meta(session_id)
            assert meta["title"] == "Greeting The User"
            assert "titled_at" in meta

            messages = load_session(session_id)
            assert messages == [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
            ]

    def test_set_session_title_is_noop_for_missing_session(self, tmp_path):
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            set_session_title("nope", "Whatever")
            assert get_session_title("nope") is None

    def test_list_sessions_includes_title(self, tmp_path):
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            session_id = create_session()
            set_session_title(session_id, "My Topic")

            sessions = list_sessions()
            match = [s for s in sessions if s["id"] == session_id][0]
            assert match["title"] == "My Topic"

    def test_get_session_title_rejects_blank(self, tmp_path):
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            session_id = create_session()
            rewrite_session(session_id, [], meta_updates={"title": "   "})
            assert get_session_title(session_id) is None

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

    def test_list_recent_sessions_returns_newest_first_with_preview_and_count(self, tmp_path):
        _write_session_file(
            tmp_path,
            session_id="older",
            created="2026-04-10T10:00:00",
            title="Old Session",
            messages=[{"role": "user", "content": "older preview"}],
        )
        _write_session_file(
            tmp_path,
            session_id="newer",
            created="2026-04-11T10:00:00",
            title="New Session",
            messages=[
                {"role": "user", "content": "newer preview"},
                {"role": "assistant", "content": "reply"},
            ],
        )
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            result = list_recent_sessions(limit=2)

        assert result["success"] is True
        assert result["mode"] == "recent"
        assert [item["session_id"] for item in result["results"]] == ["newer", "older"]
        assert result["results"][0]["message_count"] == 2
        assert result["results"][0]["preview"] == "newer preview"

    def test_list_recent_sessions_excludes_current_session(self, tmp_path):
        _write_session_file(
            tmp_path,
            session_id="current",
            created="2026-04-11T10:00:00",
            messages=[{"role": "user", "content": "current"}],
        )
        _write_session_file(
            tmp_path,
            session_id="other",
            created="2026-04-10T10:00:00",
            messages=[{"role": "user", "content": "other"}],
        )
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            result = list_recent_sessions(limit=2, exclude_session_id="current")

        assert [item["session_id"] for item in result["results"]] == ["other"]

    def test_search_sessions_title_match_outranks_body_only_match(self, tmp_path):
        _write_session_file(
            tmp_path,
            session_id="title_hit",
            created="2026-04-15T10:00:00",
            title="Clarify Callback Wiring",
            messages=[{"role": "assistant", "content": "some unrelated content"}],
        )
        _write_session_file(
            tmp_path,
            session_id="body_hit",
            created="2026-04-20T10:00:00",
            title="Different topic",
            messages=[{"role": "assistant", "content": "We added clarify callback support here."}],
        )
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            result = search_sessions("clarify callback", limit=2)

        assert result["success"] is True
        assert [item["session_id"] for item in result["results"]] == ["title_hit", "body_hit"]

    def test_search_sessions_finds_tool_output_with_lower_weight(self, tmp_path):
        _write_session_file(
            tmp_path,
            session_id="tool_hit",
            created="2026-04-20T10:00:00",
            messages=[{"role": "tool", "content": "Shell error: sqlite database is locked"}],
        )
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            result = search_sessions("database locked", limit=3)

        assert result["count"] == 1
        assert result["results"][0]["session_id"] == "tool_hit"
        assert result["results"][0]["snippets"][0]["role"] == "tool"

    def test_search_sessions_role_filter_ignores_other_roles(self, tmp_path):
        _write_session_file(
            tmp_path,
            session_id="mixed",
            created="2026-04-20T10:00:00",
            messages=[
                {"role": "assistant", "content": "clarify callback lives here"},
                {"role": "tool", "content": "clarify callback tool output"},
            ],
        )
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            tool_only = search_sessions("clarify callback", role_filter="tool", limit=3)
            assistant_only = search_sessions("clarify callback", role_filter="assistant", limit=3)

        assert tool_only["count"] == 1
        assert tool_only["results"][0]["snippets"][0]["role"] == "tool"
        assert assistant_only["count"] == 1
        assert assistant_only["results"][0]["snippets"][0]["role"] == "assistant"

    def test_search_sessions_is_case_insensitive_and_normalizes_punctuation(self, tmp_path):
        _write_session_file(
            tmp_path,
            session_id="punct",
            created="2026-04-20T10:00:00",
            title="Clarify, Callback!",
            messages=[{"role": "assistant", "content": "ignored"}],
        )
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            result = search_sessions("clarify callback", limit=3)

        assert result["count"] == 1
        assert result["results"][0]["session_id"] == "punct"

    def test_search_sessions_excludes_current_session(self, tmp_path):
        _write_session_file(
            tmp_path,
            session_id="current",
            created="2026-04-20T10:00:00",
            title="Clarify Callback",
            messages=[{"role": "assistant", "content": "clarify callback"}],
        )
        _write_session_file(
            tmp_path,
            session_id="other",
            created="2026-04-19T10:00:00",
            title="Different Clarify Callback",
            messages=[{"role": "assistant", "content": "clarify callback"}],
        )
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            result = search_sessions("clarify callback", exclude_session_id="current", limit=3)

        assert [item["session_id"] for item in result["results"]] == ["other"]

    def test_search_sessions_skips_invalid_json_lines(self, tmp_path):
        _write_session_file(
            tmp_path,
            session_id="bad",
            created="2026-04-20T10:00:00",
            title="Bad Session",
            messages=[{"role": "assistant", "content": "clarify callback works"}],
            bad_lines=["{not json}"],
        )
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            result = search_sessions("clarify callback", limit=3)

        assert result["count"] == 1
        assert result["results"][0]["session_id"] == "bad"

    def test_search_sessions_returns_empty_when_no_match(self, tmp_path):
        _write_session_file(
            tmp_path,
            session_id="one",
            created="2026-04-20T10:00:00",
            title="Totally different",
            messages=[{"role": "assistant", "content": "nothing relevant"}],
        )
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            result = search_sessions("clarify callback", limit=3)

        assert result["success"] is True
        assert result["count"] == 0
        assert result["results"] == []

    def test_search_sessions_limits_snippets_to_three(self, tmp_path):
        _write_session_file(
            tmp_path,
            session_id="many",
            created="2026-04-20T10:00:00",
            messages=[
                {"role": "assistant", "content": "clarify callback one"},
                {"role": "assistant", "content": "clarify callback two"},
                {"role": "assistant", "content": "clarify callback three"},
                {"role": "assistant", "content": "clarify callback four"},
            ],
        )
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
            result = search_sessions("clarify callback", limit=3)

        assert len(result["results"][0]["snippets"]) == 3
