"""Tests for the interactive setup wizard."""

from __future__ import annotations

from typing import List

import pytest
import yaml

from astra_claw.cli import setup as wizard_mod
from astra_claw.cli.setup import run_setup


@pytest.fixture(autouse=True)
def _astraclaw_home(tmp_path, monkeypatch):
    """Redirect ASTRACLAW_HOME and clear provider env so tests are hermetic."""
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    # Pretend we have a TTY so the non-interactive guard doesn't trip.
    monkeypatch.setattr(wizard_mod, "is_interactive_stdin", lambda: True)
    yield


class _ScriptedInput:
    """Replays a list of canned responses for ``input()`` calls."""

    def __init__(self, answers: List[str]):
        self._answers = list(answers)
        self.calls: List[str] = []

    def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        if not self._answers:
            raise AssertionError(f"Wizard asked an unexpected prompt: {prompt!r}")
        return self._answers.pop(0)


class _ScriptedChoice:
    """Replays a list of canned numeric choices."""

    def __init__(self, choices: List[int]):
        self._choices = list(choices)
        self.calls: List[tuple[str, list[str], int]] = []

    def __call__(self, question: str, choices: list, default_index: int) -> int:
        self.calls.append((question, list(choices), default_index))
        if not self._choices:
            raise AssertionError(f"Wizard asked an unexpected choice: {question!r}")
        return self._choices.pop(0)


def _fake_validator_ok(provider: str, key: str):
    return True, ""


def _fake_validator_bad(provider: str, key: str):
    return False, "rejected"


def test_full_setup_writes_config(tmp_path):
    inputs = _ScriptedInput(["sk-good"])
    choices = _ScriptedChoice([0, 1])  # provider OpenAI, model index 1

    rc = run_setup(
        section="all",
        input_fn=inputs,
        choice_fn=choices,
        validate_fn=_fake_validator_ok,
    )

    assert rc == 0
    config_path = tmp_path / "config.yaml"
    assert config_path.exists()
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert data["model"]["provider"] == "openai"
    assert data["model"]["api_key"] == "sk-good"
    assert data["model"]["default"] == "gpt-5.4"


def test_setup_validation_rejects_bad_key_then_aborts(tmp_path):
    # First validation fails, then the user declines to retry.
    inputs = _ScriptedInput(["sk-bad", "n"])
    choices = _ScriptedChoice([1])  # OpenRouter

    rc = run_setup(
        section="all",
        input_fn=inputs,
        choice_fn=choices,
        validate_fn=_fake_validator_bad,
    )

    assert rc == 1
    assert not (tmp_path / "config.yaml").exists()


def test_section_model_only_skips_provider_and_key(tmp_path):
    # Pre-seed an existing config so the model-only run has somewhere to start.
    initial = {
        "model": {
            "provider": "openai",
            "api_key": "sk-existing",
            "default": "gpt-5.4-mini",
        }
    }
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(initial), encoding="utf-8"
    )

    inputs = _ScriptedInput([])  # the model step uses choice-only for curated picks
    choices = _ScriptedChoice([2])  # gpt-4o-mini (third in OpenAI list)

    rc = run_setup(
        section="model",
        input_fn=inputs,
        choice_fn=choices,
        validate_fn=_fake_validator_ok,
    )

    assert rc == 0
    data = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert data["model"]["provider"] == "openai"
    assert data["model"]["api_key"] == "sk-existing"
    assert data["model"]["default"] == "gpt-4o-mini"


def test_keep_existing_key_skips_validation(tmp_path):
    initial = {
        "model": {
            "provider": "openai",
            "api_key": "sk-existing",
            "default": "gpt-5.4-mini",
        }
    }
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(initial), encoding="utf-8"
    )

    inputs = _ScriptedInput(["", ""])  # step 2 keeps key; if we hit any extra prompt this raises
    choices = _ScriptedChoice([0, 0])  # provider openai, model index 0

    def _validator_should_not_run(provider, key):
        raise AssertionError("validator should not be called when keeping existing key")

    rc = run_setup(
        section="all",
        input_fn=inputs,
        choice_fn=choices,
        validate_fn=_validator_should_not_run,
    )

    assert rc == 0
    data = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert data["model"]["api_key"] == "sk-existing"


def test_unknown_section_returns_error(tmp_path):
    rc = run_setup(
        section="banana",
        input_fn=_ScriptedInput([]),
        choice_fn=_ScriptedChoice([]),
        validate_fn=_fake_validator_ok,
    )
    assert rc == 2
    assert not (tmp_path / "config.yaml").exists()


def test_custom_model_path(tmp_path):
    inputs = _ScriptedInput(["sk-good", "my-org/custom-model"])
    # provider openai (0), then "Custom model name" (last entry = index 3)
    choices = _ScriptedChoice([0, 3])

    rc = run_setup(
        section="all",
        input_fn=inputs,
        choice_fn=choices,
        validate_fn=_fake_validator_ok,
    )

    assert rc == 0
    data = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert data["model"]["default"] == "my-org/custom-model"


def test_provider_change_clears_existing_key(tmp_path):
    initial = {
        "model": {
            "provider": "openai",
            "api_key": "sk-old",
            "default": "gpt-5.4-mini",
        }
    }
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(initial), encoding="utf-8"
    )

    # Switch provider to OpenRouter, then enter a fresh key, then pick model 0.
    inputs = _ScriptedInput(["sk-router"])
    choices = _ScriptedChoice([1, 0])

    rc = run_setup(
        section="all",
        input_fn=inputs,
        choice_fn=choices,
        validate_fn=_fake_validator_ok,
    )

    assert rc == 0
    data = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert data["model"]["provider"] == "openrouter"
    assert data["model"]["api_key"] == "sk-router"
