"""Clarify tool - pause and ask the user one structured question.

Thin shell: schema + validation + delegates to a platform-provided callback.
The CLI layer owns the actual interaction UI. Same pattern as memory_tool /
todo_tool: the registry handler runs with no callback (returns an
"unavailable" error JSON), and agent/tool_runner.py special-cases the name
to inject the CLI's callback.
"""

from __future__ import annotations

import json
from typing import Any, Callable, List, Optional

from .registry import registry


MAX_CHOICES = 4


def clarify_tool(
    question: str,
    choices: Any = None,
    callback: Optional[Callable[[str, Optional[List[str]]], str]] = None,
) -> str:
    """Ask the user a question, optionally with multiple-choice options.

    Returns a JSON string. `callback(question, choices) -> str` is supplied
    by the platform layer (CLI / gateway). When missing we return an error
    JSON so the agent can keep going instead of hanging.
    """
    if not isinstance(question, str) or not question.strip():
        return json.dumps({"error": "Question text is required."}, ensure_ascii=False)

    question = question.strip()

    if choices is not None:
        if not isinstance(choices, list):
            return json.dumps(
                {"error": "choices must be a list of strings."},
                ensure_ascii=False,
            )
        cleaned = [str(c).strip() for c in choices if str(c).strip()]
        if len(cleaned) > MAX_CHOICES:
            cleaned = cleaned[:MAX_CHOICES]
        choices = cleaned or None

    if callback is None:
        return json.dumps(
            {"error": "Clarify tool is not available in this execution context."},
            ensure_ascii=False,
        )

    try:
        user_response = callback(question, choices)
    except Exception as exc:
        return json.dumps(
            {"error": f"Failed to get user input: {exc}"},
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "question": question,
            "choices_offered": choices,
            "user_response": str(user_response).strip(),
        },
        ensure_ascii=False,
    )


def _check_clarify_available() -> bool:
    return True


CLARIFY_SCHEMA = {
    "name": "clarify",
    "description": (
        "Ask the user a question when you need clarification, feedback, or a "
        "decision before proceeding. Two modes:\n\n"
        "1. Multiple choice: provide up to 4 choices. The UI appends an "
        "'Other (type your answer)' option automatically.\n"
        "2. Open-ended: omit the choices parameter and the user types a free "
        "response.\n\n"
        "Use this when the request is genuinely ambiguous and a wrong guess "
        "would waste work. Do NOT use it for low-stakes defaults you can "
        "pick yourself, or for yes/no confirmation of dangerous commands "
        "(shell has its own approval flow)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question to present to the user.",
            },
            "choices": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": MAX_CHOICES,
                "description": (
                    "Up to 4 answer choices. Omit this parameter entirely for "
                    "an open-ended question."
                ),
            },
        },
        "required": ["question"],
    },
}


registry.register(
    name="clarify",
    toolset="clarify",
    schema=CLARIFY_SCHEMA,
    handler=lambda args: clarify_tool(
        question=args.get("question", ""),
        choices=args.get("choices"),
        callback=None,
    ),
    check_fn=_check_clarify_available,
)
