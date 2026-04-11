"""Tests for core astra-claw features.

Covers: constants, config, tool registry, prompt_builder, and registry smoke checks.
No API key required -- these are pure unit tests.

Run:
    python -m pytest tests/test_features.py -v
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

from astra_claw.agent.prompt_builder import build_system_prompt
from astra_claw.config import DEFAULT_CONFIG, _deep_merge, ensure_astraclaw_home, load_config
from astra_claw.constants import get_astraclaw_home
from astra_claw.tools import file_tools  # noqa: F401
from astra_claw.tools.registry import ToolRegistry
from astra_claw.tools.registry import registry as global_registry


class TestConstants:
    def test_default_home(self):
        """Default home should be ~/.astraclaw when env var is unset."""
        env = os.environ.copy()
        env.pop("ASTRACLAW_HOME", None)
        with patch.dict(os.environ, env, clear=True):
            home = get_astraclaw_home()
            assert home == Path.home() / ".astraclaw"

    def test_custom_home_via_env(self, tmp_path):
        """ASTRACLAW_HOME env var overrides the default."""
        custom = str(tmp_path / "custom_home")
        with patch.dict(os.environ, {"ASTRACLAW_HOME": custom}):
            assert get_astraclaw_home() == Path(custom)


class TestConfig:
    def test_ensure_home_creates_dirs(self, tmp_path):
        """ensure_astraclaw_home() should create home + subdirs."""
        home = tmp_path / "astraclaw_test"
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(home)}):
            result = ensure_astraclaw_home()
            assert result == home
            for subdir in ("sessions", "memory", "skills", "logs"):
                assert (home / subdir).is_dir()

    def test_ensure_home_idempotent(self, tmp_path):
        """Calling ensure_astraclaw_home() twice should not raise."""
        home = tmp_path / "astraclaw_test"
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(home)}):
            ensure_astraclaw_home()
            ensure_astraclaw_home()

    def test_deep_merge_simple(self):
        base = {"a": 1, "b": 2}
        override = {"b": 99, "c": 3}
        assert _deep_merge(base, override) == {"a": 1, "b": 99, "c": 3}

    def test_deep_merge_nested(self):
        base = {"model": {"default": "gpt-4o-mini", "provider": "openai"}}
        override = {"model": {"default": "gpt-4o"}}
        result = _deep_merge(base, override)
        assert result["model"]["default"] == "gpt-4o"
        assert result["model"]["provider"] == "openai"

    def test_deep_merge_does_not_mutate_base(self):
        base = {"a": {"x": 1}}
        override = {"a": {"x": 2}}
        _deep_merge(base, override)
        assert base["a"]["x"] == 1

    def test_load_config_defaults(self, tmp_path):
        """load_config() returns defaults when no config.yaml exists."""
        home = tmp_path / "astraclaw_test"
        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(home)}):
            config = load_config()
            assert config["model"]["default"] == DEFAULT_CONFIG["model"]["default"]
            assert config["agent"]["max_turns"] == DEFAULT_CONFIG["agent"]["max_turns"]

    def test_load_config_with_override(self, tmp_path):
        """load_config() merges user config.yaml on top of defaults."""
        home = tmp_path / "astraclaw_test"
        home.mkdir(parents=True)
        config_file = home / "config.yaml"
        config_file.write_text("model:\n  default: gpt-4o\nagent:\n  max_turns: 50\n")

        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(home)}):
            config = load_config()
            assert config["model"]["default"] == "gpt-4o"
            assert config["model"]["provider"] == "openai"
            assert config["agent"]["max_turns"] == 50

    def test_load_config_bad_yaml(self, tmp_path):
        """load_config() handles corrupt yaml gracefully (returns defaults)."""
        home = tmp_path / "astraclaw_test"
        home.mkdir(parents=True)
        (home / "config.yaml").write_text(": : : not valid yaml [[[")

        with patch.dict(os.environ, {"ASTRACLAW_HOME": str(home)}):
            config = load_config()
            assert config["model"]["default"] == DEFAULT_CONFIG["model"]["default"]


class TestToolRegistry:
    def test_register_and_get_definitions(self):
        reg = ToolRegistry()
        schema = {"name": "dummy", "description": "test", "parameters": {"type": "object", "properties": {}}}
        reg.register("dummy", "test", schema, lambda args: json.dumps({"ok": True}))

        defs = reg.get_definitions()
        assert len(defs) == 1
        assert defs[0]["type"] == "function"
        assert defs[0]["function"]["name"] == "dummy"

    def test_dispatch_success(self):
        reg = ToolRegistry()
        schema = {"name": "echo", "description": "echo", "parameters": {"type": "object", "properties": {}}}
        reg.register("echo", "test", schema, lambda args: json.dumps({"msg": args.get("text", "")}))

        result = json.loads(reg.dispatch("echo", {"text": "hello"}))
        assert result["msg"] == "hello"

    def test_dispatch_unknown_tool(self):
        reg = ToolRegistry()
        result = json.loads(reg.dispatch("nonexistent", {}))
        assert "error" in result
        assert "Unknown tool" in result["error"]

    def test_dispatch_handler_exception(self):
        reg = ToolRegistry()
        schema = {"name": "bomb", "description": "explodes", "parameters": {"type": "object", "properties": {}}}
        reg.register("bomb", "test", schema, lambda args: (_ for _ in ()).throw(ValueError("boom")))

        def bad_handler(args):
            raise ValueError("boom")

        reg._tools["bomb"]["handler"] = bad_handler
        result = json.loads(reg.dispatch("bomb", {}))
        assert "error" in result
        assert "ValueError" in result["error"]

    def test_empty_registry(self):
        reg = ToolRegistry()
        assert reg.get_definitions() == []

    def test_get_definitions_filters_by_toolset(self):
        reg = ToolRegistry()
        schema_a = {"name": "a", "description": "a", "parameters": {"type": "object", "properties": {}}}
        schema_b = {"name": "b", "description": "b", "parameters": {"type": "object", "properties": {}}}
        reg.register("a", "filesystem", schema_a, lambda args: json.dumps({"ok": True}))
        reg.register("b", "terminal", schema_b, lambda args: json.dumps({"ok": True}))

        defs = reg.get_definitions(enabled_toolsets={"filesystem"})

        assert [d["function"]["name"] for d in defs] == ["a"]

    def test_get_definitions_skips_tool_when_check_fails(self):
        reg = ToolRegistry()
        schema = {"name": "guarded", "description": "guarded", "parameters": {"type": "object", "properties": {}}}
        reg.register(
            "guarded",
            "web",
            schema,
            lambda args: json.dumps({"ok": True}),
            check_fn=lambda: False,
        )

        assert reg.get_definitions() == []

    def test_get_definitions_skips_tool_when_check_raises(self):
        reg = ToolRegistry()
        schema = {"name": "guarded", "description": "guarded", "parameters": {"type": "object", "properties": {}}}

        def bad_check():
            raise RuntimeError("nope")

        reg.register(
            "guarded",
            "web",
            schema,
            lambda args: json.dumps({"ok": True}),
            check_fn=bad_check,
        )

        assert reg.get_definitions() == []

    def test_get_definitions_includes_tool_when_check_passes(self):
        reg = ToolRegistry()
        schema = {"name": "guarded", "description": "guarded", "parameters": {"type": "object", "properties": {}}}
        reg.register(
            "guarded",
            "web",
            schema,
            lambda args: json.dumps({"ok": True}),
            check_fn=lambda: True,
        )

        defs = reg.get_definitions(enabled_toolsets={"web"})

        assert [d["function"]["name"] for d in defs] == ["guarded"]


class TestPromptBuilder:
    def test_returns_string(self):
        prompt = build_system_prompt()
        assert isinstance(prompt, str)

    def test_contains_identity(self):
        prompt = build_system_prompt()
        assert "Astra-Claw" in prompt

    def test_not_empty(self):
        assert len(build_system_prompt()) > 0

    def test_windows_prompt_mentions_cmd_compatible_shell(self):
        with patch("platform.system", return_value="Windows"):
            prompt = build_system_prompt()
        assert "cmd-compatible" in prompt
        assert "findstr" in prompt


class TestGlobalRegistry:
    def test_read_file_registered(self):
        """The global registry should have read_file after importing file_tools."""
        names = [d["function"]["name"] for d in global_registry.get_definitions()]
        assert "read_file" in names
