"""Skills tool — list installed skills or load raw SKILL.md content."""

from __future__ import annotations

import json

from ..cli.skills import MAX_SKILL_BYTES, find_skill, list_skills
from .registry import registry


def _success(**payload) -> str:
    return json.dumps({"success": True, **payload}, ensure_ascii=False)


def _error(message: str) -> str:
    return json.dumps({"success": False, "error": message}, ensure_ascii=False)


def skills_tool(action: str, name: str | None = None) -> str:
    action = (action or "").strip().lower()
    if action not in {"list", "view"}:
        return _error("action must be 'list' or 'view'")

    if action == "list":
        skills = list_skills()
        return _success(
            action="list",
            count=len(skills),
            skills=[
                {
                    "name": skill.name,
                    "description": skill.description,
                    "command": skill.command,
                }
                for skill in skills
            ],
        )

    skill_name = (name or "").strip()
    if not skill_name:
        return _error("name is required when action is 'view'")

    skill = find_skill(skill_name)
    if skill is None:
        return _error(f"Unknown skill: {skill_name}")

    raw = skill.path.read_bytes()
    if len(raw) > MAX_SKILL_BYTES:
        return _error(f"Skill file is too large: {skill.path}")

    content = raw.decode("utf-8", errors="replace")
    return _success(
        action="view",
        name=skill.name,
        description=skill.description,
        content=content,
    )


def _skills_tool_available() -> bool:
    return bool(list_skills())


SKILLS_SCHEMA = {
    "name": "skills",
    "description": (
        "List installed skills or load a skill's full SKILL.md instructions. "
        "Use 'list' to see available skills. Use 'view' when a skill seems "
        "relevant and you need its full workflow before acting."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "view"],
                "description": "list = metadata only; view = full SKILL.md content.",
            },
            "name": {
                "type": "string",
                "description": "Skill slug. Required for 'view'.",
            },
        },
        "required": ["action"],
    },
}


registry.register(
    name="skills",
    toolset="skills",
    schema=SKILLS_SCHEMA,
    handler=lambda args: skills_tool(
        action=args.get("action", ""),
        name=args.get("name"),
    ),
    check_fn=_skills_tool_available,
)