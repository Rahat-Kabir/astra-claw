"""Tests for config.save_user_config and load_user_config."""

import yaml

from astra_claw.config import (
    load_config,
    load_user_config,
    save_user_config,
)


def test_save_user_config_writes_only_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))

    path = save_user_config({"model": {"provider": "openai", "default": "gpt-4o-mini"}})

    assert path == tmp_path / "config.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data == {"model": {"provider": "openai", "default": "gpt-4o-mini"}}


def test_save_user_config_merges_into_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))

    save_user_config({"model": {"provider": "openai", "api_key": "sk-1"}})
    save_user_config({"model": {"default": "gpt-5.4-mini"}})

    data = load_user_config()
    assert data["model"] == {
        "provider": "openai",
        "api_key": "sk-1",
        "default": "gpt-5.4-mini",
    }


def test_load_config_merges_user_overrides_on_top_of_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))

    save_user_config({"model": {"default": "custom-model"}})

    cfg = load_config()
    assert cfg["model"]["default"] == "custom-model"
    # Defaults still present for keys the user didn't override.
    assert cfg["model"]["provider"] == "openai"
    assert cfg["agent"]["max_turns"] == 20


def test_load_user_config_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    assert load_user_config() == {}
