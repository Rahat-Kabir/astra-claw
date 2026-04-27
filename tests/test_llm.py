"""Tests for llm helpers added for the setup wizard."""

from unittest.mock import patch, MagicMock

import pytest

from astra_claw import llm


def test_resolve_api_key_prefers_config(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    key = llm.resolve_api_key("openai", {"api_key": "config-key"})
    assert key == "config-key"


def test_resolve_api_key_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    key = llm.resolve_api_key("openai", {})
    assert key == "env-key"


def test_resolve_api_key_returns_empty_when_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert llm.resolve_api_key("openai", {}) == ""


def test_create_client_uses_explicit_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    captured = {}

    class FakeOpenAI:
        def __init__(self, base_url, api_key):
            captured["base_url"] = base_url
            captured["api_key"] = api_key

    with patch.object(llm, "OpenAI", FakeOpenAI):
        llm.create_client("openai", api_key="explicit")

    assert captured["api_key"] == "explicit"
    assert captured["base_url"] == llm.PROVIDER_BASE_URLS["openai"]


def test_create_client_raises_when_no_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="No API key"):
        llm.create_client("openai")


def test_validate_credentials_success():
    fake_client = MagicMock()
    fake_client.models.list.return_value = MagicMock(data=[])
    with patch.object(llm, "OpenAI", return_value=fake_client):
        ok, msg = llm.validate_credentials("openai", "sk-good")
    assert ok is True
    assert msg == ""


def test_validate_credentials_unauthorized():
    err = Exception("unauthorized")
    setattr(err, "status_code", 401)

    fake_client = MagicMock()
    fake_client.models.list.side_effect = err
    with patch.object(llm, "OpenAI", return_value=fake_client):
        ok, msg = llm.validate_credentials("openai", "sk-bad")
    assert ok is False
    assert "unauthorized" in msg.lower()


def test_validate_credentials_timeout():
    fake_client = MagicMock()
    fake_client.models.list.side_effect = Exception("Connection timed out")
    with patch.object(llm, "OpenAI", return_value=fake_client):
        ok, msg = llm.validate_credentials("openai", "sk-x", timeout=1)
    assert ok is False
    assert "timed out" in msg.lower()


def test_validate_credentials_empty_key():
    ok, msg = llm.validate_credentials("openai", "")
    assert ok is False
    assert "empty" in msg.lower()
