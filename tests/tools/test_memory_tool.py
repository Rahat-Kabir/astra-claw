"""Tests for astra_claw.tools.memory_tool wrapper."""

import json

import pytest

from astra_claw.memory import MemoryStore
from astra_claw.tools.memory_tool import MEMORY_SCHEMA, memory_tool
from astra_claw.tools.registry import registry


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    s = MemoryStore(memory_char_limit=500, user_char_limit=500)
    s.load_from_disk()
    return s


def test_schema_shape():
    assert MEMORY_SCHEMA["name"] == "memory"
    props = MEMORY_SCHEMA["parameters"]["properties"]
    assert set(props["action"]["enum"]) == {"add", "replace", "remove"}
    assert set(props["target"]["enum"]) == {"memory", "user"}
    assert MEMORY_SCHEMA["parameters"]["required"] == ["action", "target"]


def test_returns_json_string(store):
    out = memory_tool(action="add", target="memory", content="hi", store=store)
    assert isinstance(out, str)
    parsed = json.loads(out)
    assert parsed["success"] is True


def test_missing_store_errors():
    out = memory_tool(action="add", target="memory", content="hi", store=None)
    parsed = json.loads(out)
    assert parsed["success"] is False
    assert "unavailable" in parsed["error"].lower()


def test_invalid_target(store):
    out = memory_tool(action="add", target="bogus", content="hi", store=store)
    parsed = json.loads(out)
    assert parsed["success"] is False
    assert "Invalid target" in parsed["error"]


def test_invalid_action(store):
    out = memory_tool(action="nuke", target="memory", content="x", store=store)
    parsed = json.loads(out)
    assert parsed["success"] is False
    assert "Unknown action" in parsed["error"]


def test_add_requires_content(store):
    out = memory_tool(action="add", target="memory", store=store)
    parsed = json.loads(out)
    assert parsed["success"] is False


def test_replace_requires_old_text_and_content(store):
    out = memory_tool(action="replace", target="memory", content="x", store=store)
    assert json.loads(out)["success"] is False
    out = memory_tool(action="replace", target="memory", old_text="x", store=store)
    assert json.loads(out)["success"] is False


def test_remove_requires_old_text(store):
    out = memory_tool(action="remove", target="memory", store=store)
    assert json.loads(out)["success"] is False


def test_registered_in_registry_standalone_errors():
    # The registered handler has no store wired, so direct dispatch must error JSON.
    result = registry.dispatch("memory", {"action": "add", "target": "memory", "content": "x"})
    parsed = json.loads(result)
    assert parsed["success"] is False
    assert "unavailable" in parsed["error"].lower()
