"""Tests for astra_claw.tools.skills_tool."""

import json

from astra_claw.tools.registry import registry
from astra_claw.tools.skills_tool import SKILLS_SCHEMA, skills_tool


def _write_skill(root, relative_dir: str, content: str):
    skill_dir = root / "skills" / relative_dir
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text(content, encoding="utf-8")
    return path


def test_schema_shape():
    assert SKILLS_SCHEMA["name"] == "skills"
    props = SKILLS_SCHEMA["parameters"]["properties"]
    assert set(props["action"]["enum"]) == {"list", "view"}
    assert SKILLS_SCHEMA["parameters"]["required"] == ["action"]


def test_list_returns_installed_skills(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    _write_skill(
        tmp_path,
        "code-review",
        """---
name: code-review
description: Review code changes.
---

# Code Review
""",
    )

    parsed = json.loads(skills_tool(action="list"))

    assert parsed["success"] is True
    assert parsed["count"] == 1
    assert parsed["skills"][0]["name"] == "code-review"
    assert parsed["skills"][0]["description"] == "Review code changes."


def test_view_returns_raw_skill_content(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    _write_skill(
        tmp_path,
        "code-review",
        """---
name: code-review
description: Review code.
---

Start with findings.
""",
    )

    parsed = json.loads(skills_tool(action="view", name="code-review"))

    assert parsed["success"] is True
    assert parsed["name"] == "code-review"
    assert "Start with findings." in parsed["content"]


def test_view_unknown_skill(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))

    parsed = json.loads(skills_tool(action="view", name="missing"))

    assert parsed["success"] is False
    assert "Unknown skill" in parsed["error"]


def test_view_requires_name(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    _write_skill(tmp_path, "code-review", "name: code-review\n")

    parsed = json.loads(skills_tool(action="view", name=""))

    assert parsed["success"] is False
    assert "required" in parsed["error"].lower()


def test_hidden_when_no_skills_installed(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))

    names = {d["function"]["name"] for d in registry.get_definitions()}

    assert "skills" not in names


def test_visible_when_skills_installed(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    _write_skill(tmp_path, "code-review", "description: Review.\n")

    names = {d["function"]["name"] for d in registry.get_definitions()}

    assert "skills" in names


def test_registry_dispatch(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    _write_skill(tmp_path, "code-review", "description: Review.\n")

    parsed = json.loads(registry.dispatch("skills", {"action": "list"}))

    assert parsed["success"] is True
    assert parsed["count"] == 1