"""Tests for astra_claw.tools.clarify_tool."""

import json

from astra_claw.tools.clarify_tool import CLARIFY_SCHEMA, MAX_CHOICES, clarify_tool
from astra_claw.tools.registry import registry


def test_schema_shape():
    assert CLARIFY_SCHEMA["name"] == "clarify"
    params = CLARIFY_SCHEMA["parameters"]
    assert params["required"] == ["question"]
    assert params["properties"]["choices"]["maxItems"] == MAX_CHOICES


def test_empty_question_errors():
    out = clarify_tool(question="   ", callback=lambda q, c: "x")
    parsed = json.loads(out)
    assert "error" in parsed


def test_non_string_question_errors():
    out = clarify_tool(question=None, callback=lambda q, c: "x")  # type: ignore[arg-type]
    parsed = json.loads(out)
    assert "error" in parsed


def test_missing_callback_errors():
    out = clarify_tool(question="Which env?", choices=["dev", "prod"], callback=None)
    parsed = json.loads(out)
    assert "error" in parsed
    assert "not available" in parsed["error"].lower()


def test_choices_trimmed_to_max():
    captured = {}

    def cb(question, choices):
        captured["choices"] = choices
        return "a"

    clarify_tool(
        question="Pick one",
        choices=["a", "b", "c", "d", "e", "f"],
        callback=cb,
    )
    assert captured["choices"] == ["a", "b", "c", "d"]


def test_choices_blank_entries_filtered():
    captured = {}

    def cb(question, choices):
        captured["choices"] = choices
        return "x"

    clarify_tool(question="Q", choices=["  a  ", "", "  ", "b"], callback=cb)
    assert captured["choices"] == ["a", "b"]


def test_empty_choices_list_becomes_none():
    captured = {}

    def cb(question, choices):
        captured["choices"] = choices
        return "x"

    clarify_tool(question="Q", choices=["", "  "], callback=cb)
    assert captured["choices"] is None


def test_non_list_choices_errors():
    out = clarify_tool(question="Q", choices="not a list", callback=lambda q, c: "x")
    parsed = json.loads(out)
    assert "error" in parsed
    assert "list" in parsed["error"].lower()


def test_success_payload_contains_response():
    out = clarify_tool(
        question="Which env?",
        choices=["dev", "prod"],
        callback=lambda q, c: "prod",
    )
    parsed = json.loads(out)
    assert parsed["question"] == "Which env?"
    assert parsed["choices_offered"] == ["dev", "prod"]
    assert parsed["user_response"] == "prod"


def test_callback_exception_wrapped_in_error():
    def cb(question, choices):
        raise RuntimeError("boom")

    out = clarify_tool(question="Q", callback=cb)
    parsed = json.loads(out)
    assert "error" in parsed
    assert "boom" in parsed["error"]


def test_registry_standalone_returns_error():
    """The registered handler has no callback, so direct dispatch must error JSON."""
    result = registry.dispatch("clarify", {"question": "Which env?"})
    parsed = json.loads(result)
    assert "error" in parsed
    assert "not available" in parsed["error"].lower()
