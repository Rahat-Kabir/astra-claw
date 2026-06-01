"""Light Rich rendering helpers for the interactive CLI."""

import threading
import time
from pathlib import Path
from typing import Iterable, List, Mapping, Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.status import Status
from rich.table import Table

from .commands import COMMANDS, CommandDef
from .usage import UsageSnapshot


def _fmt_elapsed(secs: float) -> str:
    s = int(max(secs, 0))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m"


def _fmt_tokens(n: int) -> str:
    if n >= 10_000:
        return f"{n // 1000}k"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


class CliUI:
    """Small wrapper around Rich so REPL logic stays testable."""

    def __init__(self, console: Optional[Console] = None, *, render_markdown: bool = False):
        self.console = console or Console()
        self.render_markdown = render_markdown
        self._assistant_streamed = False
        self._status: Optional[Status] = None
        self._hb_started: Optional[float] = None
        self._hb_tools: int = 0
        self._hb_tokens: int = 0
        self._hb_label: str = "thinking"
        self._hb_stop: threading.Event = threading.Event()
        self._hb_thread: Optional[threading.Thread] = None

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

    def print_skills(self, skills: Iterable[object]) -> None:
        skills = list(skills)
        if not skills:
            self.print_warning("No skills installed.")
            self.console.print("Create one at ~/.astraclaw/skills/<name>/SKILL.md")
            return

        table = Table(title="Installed Skills")
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        table.add_column("Command", style="dim")
        for skill in skills:
            name = str(getattr(skill, "name", ""))
            description = str(getattr(skill, "description", ""))
            command = str(getattr(skill, "command", ""))
            table.add_row(name, description or "-", command)
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
        if self.render_markdown:
            return
        self._assistant_streamed = True
        self.console.print(token, end="", markup=False, highlight=False)

    def begin_assistant_response(self) -> None:
        """Reset per-turn assistant output state before streaming."""
        self._assistant_streamed = False

    def finish_assistant_response(self, full_text: str) -> None:
        """Finalize assistant output — render Markdown or trailing newline after plain stream."""
        text = (full_text or "").strip()
        if not text:
            return
        if self.render_markdown:
            self.console.print(Markdown(full_text))
            return
        if self._assistant_streamed:
            self.console.print()
            return
        self.console.print(full_text, markup=False, highlight=False)

    def set_render_markdown(self, enabled: bool) -> None:
        """Toggle Markdown rendering for assistant replies."""
        self.render_markdown = bool(enabled)

    def newline(self) -> None:
        self.console.print()

    # --- Live feedback during agent work --------------------------------

    def start_thinking(self, label: str = "thinking") -> None:
        """Start, resume, or relabel the heartbeat spinner.

        Counters (tools, tokens, elapsed start) persist across pause/resume so
        the turn-level totals survive streaming gaps.
        """
        if self._status is not None:
            self._hb_label = label
            self._refresh_heartbeat()
            return
        if self._hb_started is None:
            self._hb_started = time.monotonic()
            self._hb_tools = 0
            self._hb_tokens = 0
        self._hb_label = label
        self._status = self.console.status(
            self._render_heartbeat(),
            spinner="dots",
            spinner_style="dim",
        )
        self._status.start()
        self._hb_stop = threading.Event()
        self._hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._hb_thread.start()

    def pause_thinking(self) -> None:
        """Hide the spinner without resetting counters, so output can stream cleanly.

        A later `start_thinking` resumes with the same elapsed start and totals.
        """
        self._hb_stop.set()
        thread = self._hb_thread
        self._hb_thread = None
        if thread is not None:
            thread.join(timeout=0.5)
        if self._status is not None:
            try:
                self._status.stop()
            finally:
                self._status = None

    def stop_thinking(self) -> None:
        """Hide the spinner and reset heartbeat state. Safe to call repeatedly."""
        self.pause_thinking()
        self._hb_started = None
        self._hb_tools = 0
        self._hb_tokens = 0
        self._hb_label = "thinking"

    def bump_tool(self) -> None:
        """Increment the completed-tool counter on the heartbeat."""
        self._hb_tools += 1
        self._refresh_heartbeat()

    def bump_tokens(self, n: int) -> None:
        """Add to the rough streamed-token estimate. No-op for non-positive n."""
        if n <= 0:
            return
        self._hb_tokens += n

    def set_heartbeat_label(self, label: str) -> None:
        """Update the leading text of the heartbeat (e.g. when a tool starts)."""
        self._hb_label = label
        self._refresh_heartbeat()

    def get_heartbeat_snapshot(self) -> dict:
        """Read-only heartbeat state for /usage."""
        elapsed = None
        if self._hb_started is not None:
            elapsed = max(0.0, time.monotonic() - self._hb_started)
        return {
            "stream_tokens": self._hb_tokens,
            "tools": self._hb_tools,
            "elapsed_secs": elapsed,
            "in_progress": self._status is not None,
        }

    def print_usage_panel(self, snapshot: UsageSnapshot) -> None:
        """Render the /usage context panel."""
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="bold")
        grid.add_column()

        grid.add_row("Model", f"{snapshot.provider} / {snapshot.model}")
        grid.add_row(
            "Session",
            f"{snapshot.session_id} · {snapshot.message_count} messages",
        )
        grid.add_row("", "")

        bar = _usage_progress_bar(snapshot.context_percent)
        grid.add_row(
            "Context",
            (
                f"~{_fmt_tokens(snapshot.estimated_total)} / "
                f"{_fmt_tokens(snapshot.context_window)}  "
                f"({snapshot.context_percent}%)"
            ),
        )
        grid.add_row("", bar)
        grid.add_row(
            "Breakdown",
            (
                f"system ~{_fmt_tokens(snapshot.estimated_system)} · "
                f"tools ~{_fmt_tokens(snapshot.estimated_tools)} · "
                f"history ~{_fmt_tokens(snapshot.estimated_history)}"
            ),
        )

        if snapshot.compression_enabled:
            compact_status = (
                f"enabled · threshold ~{_fmt_tokens(snapshot.threshold_budget)} · "
                f"headroom ~{_fmt_tokens(snapshot.headroom)}"
            )
            would = "yes" if snapshot.would_compact else "no"
            if snapshot.would_compact:
                would = f"[yellow]{would}[/yellow]"
            compact_status += (
                f"\nwould compact: {would} · compactions: {snapshot.compactions}"
            )
            if snapshot.last_compacted_at:
                compact_status += f"\nlast compacted: {snapshot.last_compacted_at}"
        else:
            compact_status = "disabled"
        grid.add_row("Compact", compact_status)

        if snapshot.memory_enabled:
            grid.add_row("", "")
            grid.add_row(
                "Memory",
                _format_memory_line(
                    "agent",
                    snapshot.memory_chars,
                    snapshot.memory_limit,
                    snapshot.memory_entries,
                ),
            )
            grid.add_row(
                "",
                _format_memory_line(
                    "user",
                    snapshot.user_chars,
                    snapshot.user_limit,
                    snapshot.user_entries,
                ),
            )

        grid.add_row("", "")
        if (
            snapshot.turn_in_progress
            or snapshot.last_turn_stream_tokens
            or snapshot.last_turn_tools
        ):
            elapsed = (
                _fmt_elapsed(snapshot.last_turn_elapsed_secs)
                if snapshot.last_turn_elapsed_secs is not None
                else "—"
            )
            grid.add_row(
                "Last turn",
                (
                    f"~{_fmt_tokens(snapshot.last_turn_stream_tokens)} streamed · "
                    f"{snapshot.last_turn_tools} tool"
                    f"{'s' if snapshot.last_turn_tools != 1 else ''} · "
                    f"{elapsed}"
                ),
            )
        else:
            grid.add_row("Last turn", "—")
        grid.add_row("", "[dim]Estimates use char/4 heuristic, not billing-grade.[/dim]")

        self.console.print(
            Panel(grid, title="[bold cyan]Usage[/]", border_style="cyan")
        )

    def _render_heartbeat(self) -> str:
        parts = [self._hb_label]
        if self._hb_tools:
            parts.append(f"{self._hb_tools} tool{'s' if self._hb_tools != 1 else ''}")
        if self._hb_started is not None:
            parts.append(_fmt_elapsed(time.monotonic() - self._hb_started))
        if self._hb_tokens:
            parts.append(f"~{_fmt_tokens(self._hb_tokens)} tok")
        return f"[dim]{escape(' · '.join(parts))}[/dim]"

    def _refresh_heartbeat(self) -> None:
        if self._status is None:
            return
        try:
            self._status.update(self._render_heartbeat())
        except Exception:
            pass

    def _heartbeat_loop(self) -> None:
        while not self._hb_stop.wait(0.5):
            self._refresh_heartbeat()

    def print_clarify_question(
        self,
        question: str,
        choices: Optional[List[str]] = None,
    ) -> None:
        """Render a clarify prompt: the question plus an optional numbered list."""
        self.console.print(f"[bold cyan]?[/bold cyan] [bold]{escape(question)}[/bold]")
        if choices:
            for index, choice in enumerate(choices, start=1):
                self.console.print(f"  [cyan]{index})[/cyan] {escape(choice)}")
            other_index = len(choices) + 1
            self.console.print(
                f"  [cyan]{other_index})[/cyan] [dim]Other (type your answer)[/dim]"
            )
            self.console.print(
                "[dim]Enter a number, or type your own answer.[/dim]"
            )
        else:
            self.console.print("[dim]Type your answer.[/dim]")

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


def _usage_progress_bar(percent: int, width: int = 28) -> str:
    filled = max(0, min(width, round(width * percent / 100)))
    return f"[cyan]{'█' * filled}[/cyan][dim]{'░' * (width - filled)}[/dim]"


def _format_memory_line(
    label: str,
    chars: Optional[int],
    limit: Optional[int],
    entries: Optional[int],
) -> str:
    if chars is None or limit is None or limit <= 0:
        return f"{label}  —"
    pct = min(100, int((chars / limit) * 100))
    count = entries if entries is not None else 0
    return f"{label}  {pct}% — {chars:,}/{limit:,} chars ({count} entries)"
