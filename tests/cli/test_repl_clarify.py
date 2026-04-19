"""Tests for the CLI clarify callback used in the REPL."""

from unittest.mock import MagicMock

from astra_claw.cli.repl import _build_clarify_callback


class FakePromptSession:
    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    def prompt(self, *args, **kwargs):
        self.calls += 1
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


def _ui():
    ui = MagicMock()
    ui.stop_thinking = MagicMock()
    ui.print_clarify_question = MagicMock()
    return ui


def test_numeric_answer_resolves_to_choice_text():
    ui = _ui()
    prompt = FakePromptSession("2")
    cb = _build_clarify_callback(ui, prompt)

    result = cb("Which env?", ["dev", "prod"])

    assert result == "prod"
    ui.stop_thinking.assert_called_once()
    ui.print_clarify_question.assert_called_once_with("Which env?", ["dev", "prod"])


def test_numeric_out_of_range_is_treated_as_freetext():
    ui = _ui()
    prompt = FakePromptSession("9")
    cb = _build_clarify_callback(ui, prompt)

    assert cb("Which env?", ["dev", "prod"]) == "9"


def test_typed_text_returned_verbatim_when_choices_present():
    ui = _ui()
    prompt = FakePromptSession("staging")
    cb = _build_clarify_callback(ui, prompt)

    assert cb("Which env?", ["dev", "prod"]) == "staging"


def test_open_ended_returns_text_answer():
    ui = _ui()
    prompt = FakePromptSession("  hand-rolled answer  ")
    cb = _build_clarify_callback(ui, prompt)

    assert cb("What should the function be called?", None) == "hand-rolled answer"


def test_interrupt_returns_empty_string():
    ui = _ui()
    prompt = FakePromptSession(KeyboardInterrupt())
    cb = _build_clarify_callback(ui, prompt)

    assert cb("Q", ["a", "b"]) == ""


def test_eof_returns_empty_string():
    ui = _ui()
    prompt = FakePromptSession(EOFError())
    cb = _build_clarify_callback(ui, prompt)

    assert cb("Q", None) == ""
