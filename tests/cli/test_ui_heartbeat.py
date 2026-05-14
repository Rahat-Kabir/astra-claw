"""Tests for the heartbeat spinner state in CliUI."""

import io
import time

from rich.console import Console

from astra_claw.cli.ui import CliUI, _fmt_elapsed, _fmt_tokens


def _quiet_ui() -> CliUI:
    console = Console(file=io.StringIO(), force_terminal=False, width=120)
    return CliUI(console=console)


def test_fmt_elapsed_seconds():
    assert _fmt_elapsed(0) == "0s"
    assert _fmt_elapsed(5.9) == "5s"
    assert _fmt_elapsed(59) == "59s"


def test_fmt_elapsed_minutes():
    assert _fmt_elapsed(60) == "1m00s"
    assert _fmt_elapsed(102) == "1m42s"
    assert _fmt_elapsed(3599) == "59m59s"


def test_fmt_elapsed_hours():
    assert _fmt_elapsed(3600) == "1h00m"
    assert _fmt_elapsed(3600 + 5 * 60 + 30) == "1h05m"


def test_fmt_tokens_small():
    assert _fmt_tokens(0) == "0"
    assert _fmt_tokens(999) == "999"


def test_fmt_tokens_thousands():
    assert _fmt_tokens(1000) == "1.0k"
    assert _fmt_tokens(3200) == "3.2k"
    assert _fmt_tokens(9999) == "10.0k"


def test_fmt_tokens_tens_of_thousands():
    assert _fmt_tokens(10_000) == "10k"
    assert _fmt_tokens(125_400) == "125k"


def test_render_heartbeat_idle_shows_just_label():
    ui = _quiet_ui()
    ui._hb_label = "thinking"
    rendered = ui._render_heartbeat()
    assert "thinking" in rendered
    assert "tool" not in rendered
    assert "tok" not in rendered


def test_render_heartbeat_includes_tools_and_tokens():
    ui = _quiet_ui()
    ui._hb_label = "thinking"
    ui._hb_started = time.monotonic() - 5
    ui._hb_tools = 4
    ui._hb_tokens = 3200
    rendered = ui._render_heartbeat()
    assert "4 tools" in rendered
    assert "~3.2k tok" in rendered
    assert "s" in rendered  # some elapsed value


def test_render_heartbeat_singular_tool():
    ui = _quiet_ui()
    ui._hb_tools = 1
    rendered = ui._render_heartbeat()
    assert "1 tool" in rendered
    assert "1 tools" not in rendered


def test_bump_tool_increments_counter():
    ui = _quiet_ui()
    ui.start_thinking("thinking")
    try:
        ui.bump_tool()
        ui.bump_tool()
        ui.bump_tool()
        assert ui._hb_tools == 3
    finally:
        ui.stop_thinking()


def test_bump_tokens_ignores_non_positive():
    ui = _quiet_ui()
    ui.bump_tokens(10)
    ui.bump_tokens(0)
    ui.bump_tokens(-5)
    assert ui._hb_tokens == 10


def test_start_thinking_preserves_counters_on_relabel():
    ui = _quiet_ui()
    ui.start_thinking("thinking")
    try:
        ui.bump_tool()
        ui.bump_tokens(120)
        first_started = ui._hb_started

        ui.start_thinking("running search_files")

        assert ui._hb_label == "running search_files"
        assert ui._hb_tools == 1
        assert ui._hb_tokens == 120
        assert ui._hb_started == first_started
    finally:
        ui.stop_thinking()


def test_stop_thinking_resets_state():
    ui = _quiet_ui()
    ui.start_thinking("thinking")
    ui.bump_tool()
    ui.bump_tokens(50)
    ui.stop_thinking()

    assert ui._status is None
    assert ui._hb_started is None
    assert ui._hb_tools == 0
    assert ui._hb_tokens == 0
    assert ui._hb_thread is None


def test_stop_thinking_is_idempotent():
    ui = _quiet_ui()
    ui.stop_thinking()
    ui.stop_thinking()  # should not raise


def test_set_heartbeat_label_updates_label():
    ui = _quiet_ui()
    ui.start_thinking("thinking")
    try:
        ui.set_heartbeat_label("running write_file")
        assert ui._hb_label == "running write_file"
    finally:
        ui.stop_thinking()
