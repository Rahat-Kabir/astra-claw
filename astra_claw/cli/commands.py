"""Slash commands and prompt completion for the interactive CLI."""

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Optional

from prompt_toolkit.completion import Completer, Completion

from .context_completion import ContextReferenceCompleter


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
    CommandDef("/compact", "Compact older session context"),
    CommandDef("/skills", "List installed skills"),
    CommandDef("/skill", "Invoke a skill for one turn"),
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

    def __init__(
        self,
        skill_commands_provider: Callable[[], Mapping[str, object]] | None = None,
    ) -> None:
        self._skill_commands_provider = skill_commands_provider

    def _iter_skill_commands(self) -> Mapping[str, object]:
        if self._skill_commands_provider is None:
            return {}
        try:
            return self._skill_commands_provider() or {}
        except Exception:
            return {}

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

        for cmd, skill in sorted(self._iter_skill_commands().items()):
            if not cmd.startswith(text.lower()):
                continue
            description = str(getattr(skill, "description", "") or "Skill command")
            yield Completion(
                cmd,
                start_position=-len(text),
                display=cmd,
                display_meta=description,
            )


class AstraCompleter(Completer):
    """Complete slash commands and inline context references."""

    def __init__(self) -> None:
        from .skills import get_skill_commands

        self._slash = SlashCommandCompleter(skill_commands_provider=get_skill_commands)
        self._context_refs = ContextReferenceCompleter()

    def get_completions(self, document, complete_event):
        yield from self._slash.get_completions(document, complete_event)
        yield from self._context_refs.get_completions(document, complete_event)
