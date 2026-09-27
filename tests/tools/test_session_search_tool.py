"""Tests for astra_claw.tools.session_search_tool."""

import json
import os
from unittest.mock import patch

from astra_claw.tools.registry import registry
from astra_claw.tools.session_search_tool import SESSION_SEARCH_SCHEMA, session_search_tool


def test_schema_shape():
    assert SESSION_SEARCH_SCHEMA["name"] == "session_search"
    params = SESSION_SEARCH_SCHEMA["parameters"]
    assert params["required"] == []
    assert {"query", "role_filter", "limit"} <= set(params["properties"])


def test_empty_query_routes_to_recent_mode(tmp_path):
    with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
        out = session_search_tool(query="   ")
    parsed = json.loads(out)
    assert parsed["success"] is True
    assert parsed["mode"] == "recent"


def test_query_routes_to_search_mode(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / "one.jsonl").write_text(
        '{"type":"meta","id":"one","created":"2026-04-20T12:00:00","title":"Clarify Tool"}\n'
        '{"role":"user","content":"clarify callback wiring","ts":"2026-04-20T12:00:01"}\n',
        encoding="utf-8",
    )
    with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
        out = session_search_tool(query="clarify")
    parsed = json.loads(out)
    assert parsed["success"] is True
    assert parsed["mode"] == "search"
    assert parsed["count"] == 1
    assert parsed["results"][0]["session_id"] == "one"


def test_limit_is_capped(tmp_path):
    with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
        out = session_search_tool(query="", limit=999)
    parsed = json.loads(out)
    assert parsed["success"] is True
    assert parsed["mode"] == "recent"


def test_registry_dispatch_returns_json(tmp_path):
    with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
        out = registry.dispatch("session_search", {})
    parsed = json.loads(out)
    assert parsed["success"] is True
    assert parsed["mode"] == "recent"


def test_schema_includes_include_children_flag():
    params = SESSION_SEARCH_SCHEMA["parameters"]
    assert "include_children" in params["properties"]


def _write_real_and_child(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / "real.jsonl").write_text(
        '{"type":"meta","id":"real","created":"2026-04-20T12:00:00","title":"Real Work"}\n'
        '{"role":"assistant","content":"todo tool planning details","ts":"2026-04-20T12:00:01"}\n',
        encoding="utf-8",
    )
    (sessions_dir / "kid.jsonl").write_text(
        '{"type":"meta","id":"kid","created":"2026-04-21T12:00:00",'
        '"title":"[delegate] todo tool","parent_id":"real"}\n'
        '{"role":"assistant","content":"todo tool child scratch","ts":"2026-04-21T12:00:01"}\n',
        encoding="utf-8",
    )


def test_child_sessions_demoted_by_default(tmp_path):
    _write_real_and_child(tmp_path)
    with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
        recent = json.loads(session_search_tool(query=""))
        searched = json.loads(session_search_tool(query="todo tool"))

    assert [r["session_id"] for r in recent["results"]][0] == "real"
    assert searched["results"][0]["session_id"] == "real"
    assert searched["results"][0]["is_child"] is False
    assert searched["results"][-1]["session_id"] == "kid"
    assert searched["results"][-1]["is_child"] is True


def test_include_children_flag_passthrough(tmp_path):
    _write_real_and_child(tmp_path)
    with patch.dict(os.environ, {"ASTRACLAW_HOME": str(tmp_path)}):
        searched = json.loads(session_search_tool(query="todo tool", include_children=True))

    assert [r["session_id"] for r in searched["results"]] == ["kid", "real"]
