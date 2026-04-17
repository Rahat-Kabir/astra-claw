"""Tests for astra_claw.tools.todo_tool."""

import json

import pytest

from astra_claw.tools.registry import registry
from astra_claw.tools.todo_tool import (
    TODO_SCHEMA,
    VALID_STATUSES,
    TodoStore,
    todo_tool,
)


@pytest.fixture
def store() -> TodoStore:
    return TodoStore()


# ---- schema ---------------------------------------------------------------

def test_schema_shape():
    assert TODO_SCHEMA["name"] == "todo"
    props = TODO_SCHEMA["parameters"]["properties"]
    assert "todos" in props and "merge" in props
    assert TODO_SCHEMA["parameters"]["required"] == []
    item_props = props["todos"]["items"]["properties"]
    assert set(item_props["status"]["enum"]) == VALID_STATUSES


# ---- TodoStore.write replace + merge --------------------------------------

def test_write_replace_mode(store):
    store.write([{"id": "1", "content": "a", "status": "pending"}])
    items = store.write(
        [{"id": "2", "content": "b", "status": "pending"}],
        merge=False,
    )
    assert len(items) == 1
    assert items[0]["id"] == "2"


def test_write_merge_updates_and_appends(store):
    store.write([
        {"id": "1", "content": "a", "status": "pending"},
        {"id": "2", "content": "b", "status": "pending"},
    ])
    items = store.write(
        [
            {"id": "1", "status": "completed"},
            {"id": "3", "content": "c", "status": "pending"},
        ],
        merge=True,
    )
    assert [i["id"] for i in items] == ["1", "2", "3"]
    assert items[0]["status"] == "completed"
    assert items[0]["content"] == "a"  # not overwritten
    assert items[2]["content"] == "c"


def test_merge_skips_items_without_id(store):
    store.write([{"id": "1", "content": "a", "status": "pending"}])
    items = store.write([{"content": "ghost", "status": "pending"}], merge=True)
    assert len(items) == 1
    assert items[0]["id"] == "1"


def test_invalid_status_defaults_to_pending(store):
    items = store.write([{"id": "1", "content": "a", "status": "bogus"}])
    assert items[0]["status"] == "pending"


def test_missing_fields_are_defaulted(store):
    items = store.write([{"id": "", "content": "", "status": ""}])
    assert items[0]["id"] == "?"
    assert items[0]["content"] == "(no description)"
    assert items[0]["status"] == "pending"


# ---- todo_tool handler ----------------------------------------------------

def test_handler_returns_json_string(store):
    out = todo_tool(
        todos=[{"id": "1", "content": "a", "status": "pending"}],
        store=store,
    )
    assert isinstance(out, str)
    parsed = json.loads(out)
    assert parsed["success"] is True
    assert parsed["todos"][0]["id"] == "1"
    assert parsed["summary"]["total"] == 1
    assert parsed["summary"]["pending"] == 1


def test_handler_read_mode_returns_current_list(store):
    store.write([{"id": "1", "content": "a", "status": "in_progress"}])
    out = todo_tool(store=store)  # no todos -> read
    parsed = json.loads(out)
    assert parsed["summary"]["in_progress"] == 1
    assert len(parsed["todos"]) == 1


def test_handler_summary_counts_all_statuses(store):
    out = todo_tool(
        todos=[
            {"id": "1", "content": "a", "status": "pending"},
            {"id": "2", "content": "b", "status": "in_progress"},
            {"id": "3", "content": "c", "status": "completed"},
            {"id": "4", "content": "d", "status": "cancelled"},
        ],
        store=store,
    )
    summary = json.loads(out)["summary"]
    assert summary == {
        "total": 4,
        "pending": 1,
        "in_progress": 1,
        "completed": 1,
        "cancelled": 1,
    }


def test_handler_without_store_errors():
    out = todo_tool(todos=[], store=None)
    parsed = json.loads(out)
    assert parsed["success"] is False
    assert "unavailable" in parsed["error"].lower()


# ---- format_for_injection --------------------------------------------------

def test_format_for_injection_empty_store(store):
    assert store.format_for_injection() is None


def test_format_for_injection_all_done_returns_none(store):
    store.write([
        {"id": "1", "content": "a", "status": "completed"},
        {"id": "2", "content": "b", "status": "cancelled"},
    ])
    assert store.format_for_injection() is None


def test_format_for_injection_shows_only_active(store):
    store.write([
        {"id": "1", "content": "alpha", "status": "completed"},
        {"id": "2", "content": "beta", "status": "in_progress"},
        {"id": "3", "content": "gamma", "status": "pending"},
    ])
    out = store.format_for_injection()
    assert out is not None
    assert "alpha" not in out  # completed items are hidden
    assert "beta" in out
    assert "gamma" in out
    assert "[>]" in out and "[ ]" in out


# ---- registry integration --------------------------------------------------

def test_registered_standalone_dispatch_errors():
    # Registered handler has no store wired -> direct dispatch returns an error JSON.
    result = registry.dispatch("todo", {"todos": []})
    parsed = json.loads(result)
    assert parsed["success"] is False
    assert "unavailable" in parsed["error"].lower()


def test_registry_exposes_todo_in_planning_toolset():
    defs = registry.get_definitions(enabled_toolsets={"planning"})
    names = [d["function"]["name"] for d in defs]
    assert "todo" in names
