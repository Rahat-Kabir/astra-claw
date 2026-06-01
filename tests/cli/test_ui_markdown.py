"""Tests for optional Markdown rendering of assistant replies."""

import io

from rich.console import Console

from astra_claw.cli.ui import CliUI


def _ui_and_output(*, render_markdown: bool = False) -> tuple[CliUI, io.StringIO]:
    output = io.StringIO()
    console = Console(file=output, force_terminal=True, width=100)
    return CliUI(console, render_markdown=render_markdown), output


def test_plain_mode_streams_tokens_live():
    ui, output = _ui_and_output()
    ui.begin_assistant_response()
    ui.stream_token("hello")
    ui.stream_token(" world")
    ui.finish_assistant_response("hello world")

    assert output.getvalue() == "hello world\n"


def test_markdown_mode_buffers_during_stream():
    ui, output = _ui_and_output(render_markdown=True)
    ui.begin_assistant_response()
    ui.stream_token("**bold**")
    ui.stream_token(" text")

    assert output.getvalue() == ""


def test_markdown_mode_renders_after_turn():
    ui, output = _ui_and_output(render_markdown=True)
    ui.begin_assistant_response()
    ui.stream_token("**bold**")
    ui.finish_assistant_response("**bold**")

    rendered = output.getvalue()
    assert rendered
    assert "**bold**" not in rendered


def test_markdown_mode_prints_full_text_without_stream():
    ui, output = _ui_and_output(render_markdown=True)
    ui.begin_assistant_response()
    ui.finish_assistant_response("# Title\n\n- one")

    rendered = output.getvalue()
    assert rendered
    assert "# Title" not in rendered
    assert "one" in rendered


def test_finish_skips_empty_response():
    ui, output = _ui_and_output()
    ui.begin_assistant_response()
    ui.finish_assistant_response("   ")

    assert output.getvalue() == ""


def test_set_render_markdown_toggles_mode():
    ui, output = _ui_and_output()
    ui.set_render_markdown(True)
    ui.begin_assistant_response()
    ui.stream_token("**x**")
    ui.finish_assistant_response("**x**")

    assert "**x**" not in output.getvalue()
