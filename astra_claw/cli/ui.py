"""Light Rich rendering helpers for the interactive CLI."""

from pathlib import Path
from typing import Iterable, Mapping, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .commands import COMMANDS, CommandDef


class CliUI:
    """Small wrapper around Rich so REPL logic stays testable."""

    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()

    def print_banner(
        self,
        session_id: str,
        workspace: Optional[Path] = None,
        resumed: bool = False,
        loaded_messages: int = 0,
    ) -> None:
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="bold cyan")
        grid.add_column(style="dim")
        grid.add_row("Session", session_id)
        if workspace is not None:
            grid.add_row("Workspace", str(workspace))
        if resumed:
            grid.add_row("Loaded", f"{loaded_messages} messages")
        grid.add_row("Commands", "/help")

        self.console.print(
            Panel(
                grid,
                title="[bold cyan]Astra-Claw[/]",
                border_style="cyan",
            )
        )

    def print_help(self, commands: Iterable[CommandDef] = COMMANDS) -> None:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="cyan")
        table.add_column()
        for command in commands:
            table.add_row(command.name, command.description)

        self.console.print(Panel(table, title="Commands", border_style="cyan"))

    def print_sessions(self, sessions: list[Mapping[str, str]], limit: int = 10) -> None:
        if not sessions:
            self.print_warning("No sessions found.")
            return

        table = Table(title="Recent Sessions")
        table.add_column("ID", style="cyan")
        table.add_column("Created", style="dim")
        for session in sessions[:limit]:
            table.add_row(session.get("id", ""), session.get("created", ""))
        self.console.print(table)

    def print_error(self, message: str) -> None:
        self.console.print(f"[red]{message}[/red]")

    def print_warning(self, message: str) -> None:
        self.console.print(f"[yellow]{message}[/yellow]")

    def print_success(self, message: str) -> None:
        self.console.print(f"[green]{message}[/green]")

    def print_compaction_result(
        self,
        *,
        estimated_tokens_before: int,
        estimated_tokens_after: int,
        dropped_messages: int,
        passes: int,
    ) -> None:
        self.print_success(
            "Compacted context: "
            f"{estimated_tokens_before} -> {estimated_tokens_after} tokens, "
            f"dropped {dropped_messages} messages across {passes} pass(es)."
        )

    def stream_token(self, token: str) -> None:
        self.console.print(token, end="", markup=False, highlight=False)

    def newline(self) -> None:
        self.console.print()
