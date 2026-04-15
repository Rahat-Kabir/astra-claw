"""Slash commands and prompt completion for the interactive CLI."""

from dataclasses import dataclass
from typing import Iterable, Optional

from prompt_toolkit.completion import Completer, Completion


@dataclass(frozen=True)
class CommandDef:
    """A local CLI command handled before user text reaches the agent."""

    name: str
    description: str
    aliases: tuple[str, ...] = ()


COMMANDS: tuple[CommandDef, ...] = (
    CommandDef("/help", "Show commands"),
    CommandDef("/sessions", "List recent sessions"),
    CommandDef("/new", "Start a new session"),
    CommandDef("/exit", "Exit Astra-Claw", aliases=("/quit",)),
)

_COMMAND_BY_NAME = {command.name: command for command in COMMANDS}
for _command in COMMANDS:
    for _alias in _command.aliases:
        _COMMAND_BY_NAME[_alias] = _command


def iter_command_names(include_aliases: bool = True) -> Iterable[str]:
    """Yield command names for display and completion."""
    for command in COMMANDS:
        yield command.name
        if include_aliases:
            yield from command.aliases


def resolve_command(text: str) -> Optional[CommandDef]:
    """Return the slash command for the first token in text, if any."""
    command_name = text.strip().split(maxsplit=1)[0].lower() if text.strip() else ""
    return _COMMAND_BY_NAME.get(command_name)


class SlashCommandCompleter(Completer):
    """Complete slash commands at the start of the prompt."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/") or any(ch.isspace() for ch in text):
            return

        for name in iter_command_names(include_aliases=True):
            if name.startswith(text):
                command = resolve_command(name)
                description = command.description if command is not None else ""
                yield Completion(
                    name,
                    start_position=-len(text),
                    display=name,
                    display_meta=description,
                )
