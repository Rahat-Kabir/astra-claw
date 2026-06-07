"""Tests for the startup banner model label."""

import io

from rich.console import Console

from astra_claw.cli.ui import CliUI
from astra_claw.llm import format_route_label


def _quiet_ui() -> tuple[CliUI, io.StringIO]:
    output = io.StringIO()
    console = Console(file=output, force_terminal=False, width=120)
    return CliUI(console=console), output


def test_format_route_label_builds_provider_model_pair():
    assert format_route_label({"provider": "openai", "model": "gpt-4o"}) == "openai:gpt-4o"


def test_format_route_label_returns_empty_for_missing_route():
    assert format_route_label(None) == ""
    assert format_route_label({}) == ""
    assert format_route_label({"provider": "openai"}) == ""


def test_print_banner_includes_model_row_when_provided():
    ui, output = _quiet_ui()
    ui.print_banner(session_id="2026-06-01_abcd1234", model="openai:gpt-4o")
    rendered = output.getvalue()
    assert "Model" in rendered
    assert "openai:gpt-4o" in rendered


def test_print_banner_omits_model_row_when_not_provided():
    ui, output = _quiet_ui()
    ui.print_banner(session_id="2026-06-01_abcd1234")
    rendered = output.getvalue()
    assert "Session" in rendered
    assert "Model" not in rendered
