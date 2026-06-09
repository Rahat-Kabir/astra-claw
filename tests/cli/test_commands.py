from pathlib import Path

from prompt_toolkit.document import Document

from astra_claw.cli.commands import COMMANDS, SlashCommandCompleter, resolve_command
from astra_claw.cli.skills import SkillInfo


def _completion_texts(text: str) -> list[str]:
    completer = SlashCommandCompleter()
    return [completion.text for completion in completer.get_completions(Document(text), None)]


def test_command_registry_contains_core_commands():
    names = [command.name for command in COMMANDS]

    assert names == [
        "/help",
        "/sessions",
        "/new",
        "/compact",
        "/usage",
        "/model",
        "/retry",
        "/skills",
        "/skill",
        "/exit",
    ]


def test_quit_alias_resolves_to_exit():
    command = resolve_command("/quit")

    assert command is not None
    assert command.name == "/exit"


def test_slash_completer_suggests_matching_commands():
    assert "/help" in _completion_texts("/he")


def test_slash_completer_suggests_skill_commands():
    assert "/skill" in _completion_texts("/ski")
    assert "/skills" in _completion_texts("/ski")


def test_slash_completer_suggests_installed_skill_aliases():
    skill = SkillInfo(
        name="code-review",
        description="Review code changes.",
        path=Path("SKILL.md"),
        command="/code-review",
    )
    completer = SlashCommandCompleter(skill_commands_provider=lambda: {"/code-review": skill})

    texts = [
        completion.text
        for completion in completer.get_completions(Document("/code"), None)
    ]

    assert "/code-review" in texts


def test_slash_completer_includes_aliases():
    assert "/quit" in _completion_texts("/qu")


def test_slash_completer_ignores_normal_text():
    assert _completion_texts("normal prompt") == []


def test_slash_completer_ignores_command_arguments():
    assert _completion_texts("/help extra") == []
