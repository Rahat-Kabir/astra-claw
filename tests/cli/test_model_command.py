"""Tests for /model parsing and live model switching."""

import pytest

from astra_claw.cli.commands import parse_model_arg


def test_parse_explicit_provider_and_model():
    assert parse_model_arg("openai:gpt-4o", "openrouter") == ("openai", "gpt-4o")


def test_parse_bare_model_keeps_current_provider():
    assert parse_model_arg("gpt-4o", "openrouter") == ("openrouter", "gpt-4o")


def test_parse_strips_whitespace():
    assert parse_model_arg("  openai : gpt-4o ", "openai") == ("openai", "gpt-4o")


@pytest.mark.parametrize("bad", ["", "   ", ":gpt-4o", "openai:"])
def test_parse_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_model_arg(bad, "openai")


def test_set_primary_route_switches_in_place(monkeypatch):
    from astra_claw.agent.loop import AstraAgent

    # Stub client creation so no real key/network is needed.
    monkeypatch.setattr(AstraAgent, "_get_client", lambda self, provider: object())

    agent = AstraAgent(config={
        "model": {"provider": "openai", "default": "gpt-4o-mini"},
        "memory": {"enabled": False, "user_profile_enabled": False},
        "compression": {"enabled": False},
    })

    agent.set_primary_route("openrouter", "anthropic/claude-3.5-sonnet")

    assert agent.primary_route == {
        "provider": "openrouter",
        "model": "anthropic/claude-3.5-sonnet",
    }
    assert agent.model_config["provider"] == "openrouter"
    assert agent.model_config["default"] == "anthropic/claude-3.5-sonnet"
