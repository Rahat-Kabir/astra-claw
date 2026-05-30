from pathlib import Path

import pytest

from astra_claw.cli.skills import (
    SkillInfo,
    build_skill_invocation_message,
    build_skills_index,
    find_skill,
    get_skill_commands,
    list_skills,
    parse_skill_file,
    resolve_skill_command,
)


def _write_skill(root: Path, relative_dir: str, content: str) -> Path:
    skill_dir = root / "skills" / relative_dir
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_skill_file_uses_frontmatter(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    path = _write_skill(
        tmp_path,
        "code-review",
        """---
name: Code Review
description: Review code changes for bugs.
---

# Code Review

Start with findings.
""",
    )

    assert parse_skill_file(path) == SkillInfo(
        name="code-review",
        description="Review code changes for bugs.",
        path=path,
        command="/code-review",
    )


def test_parse_skill_file_handles_crlf_frontmatter(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    skill_dir = tmp_path / "skills" / "code-review"
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_bytes(
        b"---\r\n"
        b"name: code-review\r\n"
        b"description: Review code changes.\r\n"
        b"---\r\n"
    )

    info = parse_skill_file(path)

    assert info.name == "code-review"
    assert info.description == "Review code changes."


def test_parse_skill_file_falls_back_to_folder_and_body(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    path = _write_skill(
        tmp_path,
        "debug-python",
        """# Debug Python

Investigate tracebacks and failing tests.
""",
    )

    info = parse_skill_file(path)

    assert info.name == "debug-python"
    assert info.description == "Investigate tracebacks and failing tests."


def test_list_skills_discovers_nested_skills(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    _write_skill(tmp_path, "software/code-review", "description: ignored\n")
    _write_skill(
        tmp_path,
        "writing/release-notes",
        """---
name: release-notes
description: Write release notes.
---
""",
    )

    names = [skill.name for skill in list_skills()]

    assert names == ["code-review", "release-notes"]


def test_find_skill_accepts_slug_variants(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    _write_skill(
        tmp_path,
        "code-review",
        """---
name: Code Review
---
""",
    )

    assert find_skill("code_review").name == "code-review"
    assert find_skill("Code Review").name == "code-review"
    assert find_skill("missing") is None


def test_build_skill_invocation_message_loads_full_content(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    _write_skill(
        tmp_path,
        "code-review",
        """---
name: code-review
description: Review code.
---

# Code Review

Start with findings.
""",
    )

    message = build_skill_invocation_message("code-review", "review @diff")

    assert 'The user invoked the "code-review" skill' in message
    assert '<skill name="code-review">' in message
    assert "Start with findings." in message
    assert "User request:\nreview @diff" in message


def test_build_skill_invocation_message_rejects_missing_skill(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))

    with pytest.raises(ValueError, match="Unknown skill"):
        build_skill_invocation_message("missing", "do it")


def test_build_skills_index_lists_available_skills(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    _write_skill(
        tmp_path,
        "code-review",
        """---
name: code-review
description: Review code.
---
""",
    )

    index = build_skills_index()

    assert "## Skills" in index
    assert "- code-review: Review code." in index
    assert "<available_skills>" in index


def test_build_skills_index_empty_when_no_skills(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))

    assert build_skills_index() == ""


def test_get_skill_commands_maps_slash_aliases(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    _write_skill(
        tmp_path,
        "code-review",
        """---
name: code-review
description: Review code.
---
""",
    )

    commands = get_skill_commands()

    assert list(commands) == ["/code-review"]
    assert commands["/code-review"].name == "code-review"


def test_get_skill_commands_skips_builtin_collisions(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    _write_skill(
        tmp_path,
        "help",
        """---
name: help
description: Fake help skill.
---
""",
    )

    assert get_skill_commands() == {}


def test_resolve_skill_command_parses_optional_request(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    _write_skill(
        tmp_path,
        "code-review",
        """---
name: code-review
description: Review code.
---
""",
    )

    skill, request = resolve_skill_command("/code-review review @diff")

    assert skill.name == "code-review"
    assert request == "review @diff"


def test_resolve_skill_command_accepts_underscore_alias(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))
    _write_skill(
        tmp_path,
        "code-review",
        """---
name: code-review
description: Review code.
---
""",
    )

    skill, request = resolve_skill_command("/code_review")

    assert skill.name == "code-review"
    assert request == ""


def test_resolve_skill_command_returns_none_for_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path))

    assert resolve_skill_command("/missing") is None
    assert resolve_skill_command("hello") is None
