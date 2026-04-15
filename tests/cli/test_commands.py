from prompt_toolkit.document import Document

from astra_claw.cli.commands import COMMANDS, SlashCommandCompleter, resolve_command


def _completion_texts(text: str) -> list[str]:
    completer = SlashCommandCompleter()
    return [completion.text for completion in completer.get_completions(Document(text), None)]


def test_command_registry_contains_core_commands():
    names = [command.name for command in COMMANDS]

    assert names == ["/help", "/sessions", "/new", "/exit"]


def test_quit_alias_resolves_to_exit():
    command = resolve_command("/quit")

    assert command is not None
    assert command.name == "/exit"


def test_slash_completer_suggests_matching_commands():
    assert "/help" in _completion_texts("/he")


def test_slash_completer_includes_aliases():
    assert "/quit" in _completion_texts("/qu")


def test_slash_completer_ignores_normal_text():
    assert _completion_texts("normal prompt") == []


def test_slash_completer_ignores_command_arguments():
    assert _completion_texts("/help extra") == []
