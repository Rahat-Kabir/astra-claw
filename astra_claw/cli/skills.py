from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from astra_claw.constants import get_astraclaw_home


_SKILL_INVALID_CHARS = re.compile(r"[^a-z0-9-]")
_SKILL_MULTI_HYPHEN = re.compile(r"-{2,}")


def _slugify(value: str) -> str:
    slug = value.lower().replace("_", "-").replace(" ", "-")
    slug = _SKILL_INVALID_CHARS.sub("", slug)
    return _SKILL_MULTI_HYPHEN.sub("-", slug).strip("-")


def get_skills_dir() -> Path:
    return get_astraclaw_home() / "skills"


@dataclass(frozen=True)
class SkillInfo:
    name: str
    description: str
    path: Path
    command: str


EXCLUDED_DIRS = {
    ".git",
    ".github",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
}

MAX_SKILL_BYTES = 64_000
MAX_INDEX_DESCRIPTION = 120


def _iter_skill_files() -> list[Path]:
    skills_dir = get_skills_dir()
    if not skills_dir.exists():
        return []

    matches: list[Path] = []
    for root, dirs, files in os.walk(skills_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        if "SKILL.md" in files:
            matches.append(Path(root) / "SKILL.md")

    return sorted(matches, key=lambda path: str(path.relative_to(skills_dir)))


def _parse_frontmatter(content: str) -> tuple[dict[str, str], str]:
    # SKILL.md may use CRLF on Windows; normalize before delimiter checks.
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    if not content.startswith("---\n"):
        return {}, content

    end = content.find("\n---\n", 4)
    if end == -1:
        return {}, content

    raw_frontmatter = content[4:end]
    body = content[end + len("\n---\n"):]
    data: dict[str, str] = {}

    for line in raw_frontmatter.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            data[key] = value

    return data, body


def _first_plain_line(body: str) -> str:
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        return line[:MAX_INDEX_DESCRIPTION]
    return ""


def parse_skill_file(path: Path) -> SkillInfo:
    raw = path.read_bytes()
    if len(raw) > MAX_SKILL_BYTES:
        raise ValueError(f"Skill file is too large: {path}")

    content = raw.decode("utf-8", errors="replace")
    frontmatter, body = _parse_frontmatter(content)

    fallback_name = path.parent.name
    name = (frontmatter.get("name") or fallback_name).strip()
    slug = _slugify(name) or _slugify(fallback_name)

    description = (frontmatter.get("description") or _first_plain_line(body)).strip()
    if len(description) > MAX_INDEX_DESCRIPTION:
        description = description[: MAX_INDEX_DESCRIPTION - 3].rstrip() + "..."

    return SkillInfo(
        name=slug,
        description=description,
        path=path,
        command=f"/{slug}",
    )


def list_skills() -> list[SkillInfo]:
    skills: list[SkillInfo] = []
    seen: set[str] = set()

    for path in _iter_skill_files():
        try:
            info = parse_skill_file(path)
        except Exception:
            continue

        if not info.name or info.name in seen:
            continue

        skills.append(info)
        seen.add(info.name)

    return skills


def _reserved_slash_commands() -> set[str]:
    from .commands import iter_command_names

    return {name.lower() for name in iter_command_names(include_aliases=True)}


def get_skill_commands() -> dict[str, SkillInfo]:
    """Map ``/skill-slug`` to installed skills, excluding built-in slash commands."""
    commands: dict[str, SkillInfo] = {}
    reserved = _reserved_slash_commands()
    for skill in list_skills():
        command = skill.command.lower()
        if command in reserved:
            continue
        commands[command] = skill
    return commands


def resolve_skill_command(text: str) -> tuple[SkillInfo, str] | None:
    """Resolve ``/skill-name [request]`` when the first token is a skill alias."""
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None

    parts = stripped.split(maxsplit=1)
    cmd_key = parts[0].lower().replace("_", "-")
    user_request = parts[1].strip() if len(parts) > 1 else ""

    skill = get_skill_commands().get(cmd_key)
    if skill is None:
        return None

    return skill, user_request


def find_skill(name: str) -> SkillInfo | None:
    wanted = _slugify(name.strip())
    if not wanted:
        return None

    for skill in list_skills():
        if skill.name == wanted:
            return skill

    return None


def build_skill_invocation_message(name: str, user_request: str) -> str:
    skill = find_skill(name)
    if skill is None:
        raise ValueError(f"Unknown skill: {name}")

    raw = skill.path.read_bytes()
    if len(raw) > MAX_SKILL_BYTES:
        raise ValueError(f"Skill file is too large: {skill.path}")

    content = raw.decode("utf-8", errors="replace").strip()
    request = user_request.strip()

    parts = [
        f'[IMPORTANT: The user invoked the "{skill.name}" skill. Follow its instructions for this turn.]',
        "",
        f'<skill name="{skill.name}">',
        content,
        "</skill>",
    ]

    if request:
        parts.extend(["", "User request:", request])

    return "\n".join(parts)


def build_skills_index() -> str:
    skills = list_skills()
    if not skills:
        return ""

    lines = [
        "## Skills",
        "The user has installed optional skills. If one seems relevant, suggest using `/<skill-name> <request>` or `/skill <name> <request>`.",
        "",
        "<available_skills>",
    ]

    for skill in skills:
        if skill.description:
            lines.append(f"- {skill.name}: {skill.description}")
        else:
            lines.append(f"- {skill.name}")

    lines.append("</available_skills>")
    return "\n".join(lines)
