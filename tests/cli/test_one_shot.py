"""Exercise one-shot rendering through the real loop with a fake model stream."""

import io
from types import SimpleNamespace as NS

import pytest
from rich.console import Console

from astra_claw import __main__ as entrypoint
from astra_claw.agent import loop
from astra_claw.cli.ui import CliUI


@pytest.mark.parametrize("markdown", [False, True], ids=["plain", "markdown"])
def test_one_shot_prints_answer_once(monkeypatch, capsys, markdown):
    output = io.StringIO()
    ui = CliUI(Console(file=output, force_terminal=False, width=100))

    def stream(**kwargs):
        streamed = ""
        for text in ("**unique", " answer**"):
            yield NS(choices=[NS(delta=NS(content=text, tool_calls=None), finish_reason=None)], usage=None)
            streamed += text
            assert output.getvalue() == ("" if markdown else streamed)
        yield NS(choices=[NS(delta=NS(content=None, tool_calls=None), finish_reason="stop")], usage=None)

    client = NS(chat=NS(completions=NS(create=stream)))
    monkeypatch.setattr(loop, "create_client", lambda *args, **kwargs: client)
    agent = loop.AstraAgent(config={
        "model": {"provider": "openai", "default": "test-model", "api_key": "test-key"},
        "cli": {"render_markdown": markdown},
        "compression": {"enabled": False},
    })
    monkeypatch.setattr(entrypoint, "AstraAgent", lambda: agent)
    monkeypatch.setattr(entrypoint, "CliUI", lambda: ui)
    monkeypatch.setattr(entrypoint.sys, "argv", ["astraclaw", "hello"])
    monkeypatch.setattr(entrypoint, "set_approval_callback", lambda callback: None)

    entrypoint.main()

    # All output must pass through the UI; the streaming fallback must stay silent.
    assert capsys.readouterr().out == ""
    rendered = output.getvalue()
    assert rendered.count("unique answer") == 1
    if markdown:
        assert "**" not in rendered
    else:
        assert rendered == "**unique answer**\n"
