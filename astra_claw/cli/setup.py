"""Interactive setup wizard for Astra-Claw.

Three steps: provider, API key, model. Writes to ~/.astraclaw/config.yaml.

Section flags let users re-run a single step:
    astraclaw setup           - run all three steps
    astraclaw setup provider  - re-pick provider (and key + model that follow)
    astraclaw setup key       - re-enter API key for the current provider
    astraclaw setup model     - re-pick model for the current provider
"""

from __future__ import annotations

import sys
from typing import Any, Callable, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel

from ..config import load_user_config, save_user_config
from ..llm import PROVIDER_KEY_ENV, resolve_api_key, validate_credentials


PROVIDERS: List[Dict[str, str]] = [
    {"id": "openai", "label": "OpenAI", "hint": "API keys at https://platform.openai.com/api-keys"},
    {"id": "openrouter", "label": "OpenRouter", "hint": "API keys at https://openrouter.ai/keys"},
]

CURATED_MODELS: Dict[str, List[str]] = {
    "openai": [
        "gpt-5.4-mini",
        "gpt-5.4",
        "gpt-4o-mini",
    ],
    "openrouter": [
        "anthropic/claude-sonnet-4.6",
        "openai/gpt-5.4",
        "google/gemini-2.5-pro",
    ],
}


InputFn = Callable[[str], str]
ChoiceFn = Callable[[str, List[str], int], int]


def _default_input(prompt: str) -> str:
    return input(prompt)


def _default_choice(question: str, choices: List[str], default_index: int) -> int:
    """Numeric menu prompt. Empty input returns the default."""
    while True:
        print(question)
        for idx, choice in enumerate(choices, start=1):
            marker = " (default)" if idx - 1 == default_index else ""
            print(f"  {idx}) {choice}{marker}")
        raw = _default_input(f"Choose [{default_index + 1}]: ").strip()
        if not raw:
            return default_index
        if raw.isdigit():
            i = int(raw)
            if 1 <= i <= len(choices):
                return i - 1
        print("  Invalid choice. Try again.\n")


def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


def is_interactive_stdin() -> bool:
    return sys.stdin.isatty() if hasattr(sys.stdin, "isatty") else False


def run_setup(
    section: Optional[str] = None,
    *,
    console: Optional[Console] = None,
    input_fn: Optional[InputFn] = None,
    choice_fn: Optional[ChoiceFn] = None,
    validate_fn: Optional[Callable[[str, str], tuple[bool, str]]] = None,
) -> int:
    """Run the wizard. Returns 0 on success, non-zero on abort/error.

    The function arguments allow tests to drive the wizard without real
    stdin or network calls.
    """
    cli = console or Console()
    ask = input_fn or _default_input
    choose = choice_fn or _default_choice
    validator = validate_fn or validate_credentials

    if not is_interactive_stdin() and input_fn is None:
        cli.print(
            "[red]Astra-Claw setup needs an interactive terminal "
            "(stdin is not a TTY).[/red]"
        )
        cli.print(
            "Set keys manually in [cyan]~/.astraclaw/config.yaml[/cyan] "
            "or export the provider env var."
        )
        return 2

    cli.print(
        Panel(
            "Configure your provider, API key, and default model.\n"
            "Press Ctrl+C anytime to abort.",
            title="[bold cyan]Astra-Claw Setup[/]",
            border_style="cyan",
        )
    )

    user_cfg = load_user_config()
    model_cfg = dict(user_cfg.get("model") or {})

    section = (section or "all").lower()
    valid_sections = {"all", "provider", "key", "model"}
    if section not in valid_sections:
        cli.print(f"[red]Unknown section: {section}[/red]")
        cli.print(f"Available: {', '.join(sorted(valid_sections))}")
        return 2

    try:
        if section in {"all", "provider"}:
            model_cfg = _step_provider(cli, choose, model_cfg)

        if section in {"all", "provider", "key"}:
            ok = _step_api_key(cli, ask, validator, model_cfg)
            if not ok:
                return 1

        if section in {"all", "provider", "model"}:
            model_cfg = _step_model(cli, ask, choose, model_cfg)

        partial = {"model": model_cfg}
        path = save_user_config(partial)
    except KeyboardInterrupt:
        cli.print("\n[yellow]Setup cancelled.[/yellow]")
        return 130

    cli.print(f"\n[green]Saved configuration to[/green] [cyan]{path}[/cyan]")
    cli.print(
        f"[green]Provider:[/green] {model_cfg.get('provider')}    "
        f"[green]Model:[/green] {model_cfg.get('default')}"
    )
    cli.print("[dim]Run 'astraclaw' to start chatting.[/dim]")
    return 0


def _step_provider(
    cli: Console,
    choose: ChoiceFn,
    model_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    cli.print("\n[bold]Step 1/3 - Provider[/bold]")
    plain_labels = [f"{p['label']}  ({p['hint']})" for p in PROVIDERS]

    current = (model_cfg.get("provider") or "").strip().lower()
    default_idx = next(
        (i for i, p in enumerate(PROVIDERS) if p["id"] == current),
        0,
    )
    cli.print()
    idx = choose("Select your provider:", plain_labels, default_idx)
    chosen = PROVIDERS[idx]
    model_cfg["provider"] = chosen["id"]
    cli.print(f"[green]>[/green] Provider set to [cyan]{chosen['label']}[/cyan]")
    # Reset stored API key when provider changes - it belongs to the old one.
    if current and current != chosen["id"]:
        model_cfg.pop("api_key", None)
    return model_cfg


def _step_api_key(
    cli: Console,
    ask: InputFn,
    validator: Callable[[str, str], tuple[bool, str]],
    model_cfg: Dict[str, Any],
) -> bool:
    cli.print("\n[bold]Step 2/3 - API key[/bold]")
    provider = (model_cfg.get("provider") or "openai").strip().lower()
    env_var = PROVIDER_KEY_ENV.get(provider, "OPENAI_API_KEY")

    existing_key = resolve_api_key(provider, model_cfg)
    if existing_key:
        cli.print(
            f"Current key for [cyan]{provider}[/cyan]: "
            f"[dim]{_mask_key(existing_key)}[/dim]"
        )
        keep = ask("Keep existing key? [Y/n]: ").strip().lower()
        if keep in ("", "y", "yes"):
            cli.print("[green]>[/green] Keeping existing key (not re-validated).")
            return True

    while True:
        cli.print(
            f"\nPaste your [cyan]{provider}[/cyan] API key "
            f"(also reads from [dim]${env_var}[/dim])."
        )
        key = ask("API key: ").strip()
        if not key:
            cli.print("[yellow]No key entered. Aborting setup.[/yellow]")
            return False

        cli.print("[dim]Validating key against provider...[/dim]")
        ok, msg = validator(provider, key)
        if ok:
            cli.print("[green]>[/green] Key works.")
            model_cfg["api_key"] = key
            return True
        cli.print(f"[red]Validation failed:[/red] {msg}")
        retry = ask("Try a different key? [Y/n]: ").strip().lower()
        if retry not in ("", "y", "yes"):
            return False


def _step_model(
    cli: Console,
    ask: InputFn,
    choose: ChoiceFn,
    model_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    cli.print("\n[bold]Step 3/3 - Default model[/bold]")
    provider = (model_cfg.get("provider") or "openai").strip().lower()
    curated = CURATED_MODELS.get(provider, [])
    options = list(curated) + ["Custom model name"]

    current = (model_cfg.get("default") or "").strip()
    default_idx = curated.index(current) if current in curated else 0

    cli.print()
    idx = choose("Pick your default model:", options, default_idx)
    if idx < len(curated):
        chosen_model = curated[idx]
    else:
        while True:
            chosen_model = ask("Model id (e.g. gpt-4o-mini): ").strip()
            if chosen_model:
                break
            cli.print("[yellow]Model id cannot be empty.[/yellow]")

    model_cfg["default"] = chosen_model
    cli.print(f"[green]>[/green] Default model set to [cyan]{chosen_model}[/cyan]")
    return model_cfg
