"""Light Rich rendering helpers for the interactive CLI."""

from pathlib import Path
from typing import Iterable, Mapping, Optional

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.status import Status
from rich.table import Table

from .commands import COMMANDS, CommandDef


class CliUI:
    """Small wrapper around Rich so REPL logic stays testable."""

    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()
        self._status: Optional[Status] = None

    def print_banner(
        self,
        session_id: str,
        workspace: Optional[Path] = None,
        resumed: bool = False,
        loaded_messages: int = 0,
        title: Optional[str] = None,
    ) -> None:
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="bold cyan")
        grid.add_column(style="dim")
        grid.add_row("Session", session_id)
        if title:
            grid.add_row("Title", title)
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

    def print_sessions(self, sessions: Iterable[Mapping[str, str]], limit: int = 10) -> None:
        sessions = list(sessions)
        if not sessions:
            self.print_warning("No sessions found.")
            return

        table = Table(title="Recent Sessions")
        table.add_column("ID", style="cyan")
        table.add_column("Title", style="bold")
        table.add_column("Created", style="dim")
        for session in sessions[:limit]:
            title = session.get("title", "") or "-"
            table.add_row(
                session.get("id", ""),
                title,
                session.get("created", ""),
            )
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

    # --- Live feedback during agent work --------------------------------

    def start_thinking(self, label: str = "Thinking") -> None:
        """Show (or replace) a single dim dots spinner with `label`."""
        self.stop_thinking()
        self._status = self.console.status(
            f"[dim]{escape(label)}[/dim]",
            spinner="dots",
            spinner_style="dim",
        )
        self._status.start()

    def stop_thinking(self) -> None:
        """Hide the current spinner if any. Safe to call repeatedly."""
        if self._status is not None:
            try:
                self._status.stop()
            finally:
                self._status = None

    def print_tool_line(
        self,
        name: str,
        preview: str,
        summary: Optional[str] = None,
    ) -> None:
        """Print one compact line summarizing a completed tool call."""
        parts = [f"[cyan]{escape(name)}[/cyan]"]
        if preview:
            parts.append(f"[dim]{escape(preview)}[/dim]")
        line = "[dim]>[/dim] " + "  ".join(parts)
        if summary:
            if summary.lower().startswith("error"):
                line += f"  [red]({escape(summary)})[/red]"
            else:
                line += f"  [dim]({escape(summary)})[/dim]"
        self.console.print(line)
