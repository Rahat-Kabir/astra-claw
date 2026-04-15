# Astra-Claw - Technical Specification

## Architecture

```text
User Input
    |
__main__.py (parse args, create agent)
    |
cli/repl.py (interactive mode only)
    |
AstraAgent.run_conversation()
    |
System Prompt (prompt_builder.py)
    |
LLM Route Selection + API Call (llm.py + OpenAI SDK)
    |
Tool Calls? -> registry.dispatch() -> Append Results -> Loop back to LLM
    | (no tools)
Final Response
```

## Core Design Decisions

### Session Persistence (JSONL)

- Each session is one `.jsonl` file in `~/.astraclaw/sessions/`
- First line is metadata: `{"type": "meta", "id": "...", "created": "..."}`
- Each later line is a message with an auto-added `ts`
- `ts` is stripped before messages are replayed to the model
- JSONL was chosen over SQLite for zero dependencies and easy inspection

### Single Source of Truth for Paths

- `constants.py` exposes `get_astraclaw_home()`
- `ASTRACLAW_HOME` can override the default path
- Other modules should import this helper instead of hardcoding paths

### Tool Registry Pattern

- `tools/registry.py` contains a singleton `ToolRegistry`
- Tools self-register at import time via `registry.register()`
- Each registration now includes:
  - `name`
  - `toolset`
  - `schema`
  - `handler`
  - optional `check_fn`
- `get_definitions(enabled_toolsets=None)` only returns tools that:
  - belong to an enabled toolset, when filtering is requested
  - pass `check_fn()`, when one is provided
- `dispatch()` still executes by tool name and always returns a JSON string

### Toolset Filtering

- Built-in tools are grouped by toolset:
  - `filesystem`: `read_file`, `write_file`, `patch`, `search_files`
  - `terminal`: `shell`
  - `memory`: `memory`
- `agent/loop.py` reads optional `tools.enabled_toolsets` from config and passes that filter into the registry
- If no toolset filter is configured, all registered and available tools are exposed

### Availability Checks

- A tool may provide a `check_fn` to determine whether it should be exposed to the model
- If `check_fn()` returns `False`, the tool schema is omitted
- If `check_fn()` raises an exception, the tool is skipped rather than crashing schema generation
- This is intended for future tools that depend on API keys, installed binaries, or external services

### Search Tool

- Two modes:
  - `target="content"` uses grep/findstr-like search
  - `target="files"` uses find/dir-like filename search
- Cross-platform behavior is selected from the current OS
- Results are capped at 50 lines/files

### Shell Tool Safety

- Regex patterns detect dangerous commands such as recursive delete, `mkfs`, `dd`, SQL `DROP`, and `curl|sh`
- `set_approval_callback()` lets `__main__.py` inject an interactive approval prompt
- Without a callback, dangerous commands are blocked
- The Windows shell hint now reflects `subprocess.run(..., shell=True)` behavior more precisely: Windows commands should remain `cmd`-compatible

### CLI/TUI Layer

- Interactive mode uses `prompt_toolkit` for input history, slash command completion, and prompt handling
- Rich is used for light output: startup banner, help, session table, warnings, and errors
- Slash commands (`/help`, `/sessions`, `/new`, `/exit`, `/quit`) are handled locally and are not sent to the LLM
- `agent/loop.py` exposes an optional `stream_writer(token)` callback so the CLI owns token rendering
- When no callback is provided, the agent keeps the old stdout streaming behavior

### Memory System

- Storage: `~/.astraclaw/memory/MEMORY.md` (agent notes) and `USER.md` (user profile)
- Entries are joined by the `§` section delimiter and stored as plain text
- `MemoryStore` (in `astra_claw/memory.py`) owns persistence, char limits, and content scanning
- `tools/memory_tool.py` is a thin wrapper: schema + JSON dispatch over `MemoryStore`
- Single `memory` tool with actions `add` / `replace` / `remove` and targets `memory` / `user`
- Char limits (not token limits) keep budgets model-independent
- Frozen snapshot: `load_from_disk()` runs once at agent init; the system prompt never changes mid-session, keeping the prefix cache stable. The snapshot refreshes on the next session start.
- Content scanning rejects prompt-injection, exfiltration, and invisible-unicode payloads before persistence because entries are injected into the system prompt
- Atomic writes via temp-file + `os.replace`; no file locking (single-user CLI)
- The agent loop special-cases the `memory` tool so the handler receives the agent's `MemoryStore` instance. Standalone `registry.dispatch("memory", ...)` returns an unavailable-error JSON, keeping the registry contract uniform.
- `build_system_prompt(memory_store, include_memory_hint)` injects user and memory blocks and, when memory is enabled, appends a short hint telling the model when to save

### SOUL.md Identity Layer

- Storage: `~/.astraclaw/SOUL.md`
- `astra_claw/soul.py` owns starter-file seeding, loading, scanning, and truncation
- `ensure_astraclaw_home()` seeds a default `SOUL.md` on first run if the user does not already have one
- `load_soul_md()` returns `None` when the file is missing, empty, unreadable, or unusable; prompt assembly then falls back to `DEFAULT_IDENTITY`
- Valid `SOUL.md` content becomes slot #1 of the system prompt, ahead of memory and environment hints
- Content is security-scanned for prompt-injection / invisible-unicode payloads and truncated with a head/tail marker if oversized

### File Tools Safety

- `write_file` and `patch` share path safety helpers for workspace fence checks, protected paths, and atomic text writes
- `patch` performs exact text replacement on existing files, requires a unique match unless `replace_all=true`, and returns a unified diff
- File-writing tools block writes to sensitive paths such as `.env`, `.git`, `.ssh`, and credential-like filenames
- Blocked patterns are checked against the resolved path parts
- Workspace fence runs **before** the blocklist: when `--workspace <path>` is passed, writing tools reject any resolved path that does not sit under `get_workspace_fence()`. Fence is unset by default and falls back to cwd, so existing behavior is preserved when the flag is absent.
- Fence scope is intentionally narrow: only writing tools are jailed. `read_file` stays unfenced (reads are non-destructive) and `shell` is unfenced (chdir inheritance already scopes normal commands; fully jailing shell args is out of scope because of Windows quoting + pipes + redirects). The dangerous-command approval callback remains the defense for destructive shell usage.

### Config: Defaults + User Overrides

- `DEFAULT_CONFIG` lives in `config.py`
- User overrides are loaded from `~/.astraclaw/config.yaml`
- Nested dictionaries are deep-merged
- Optional `tools.enabled_toolsets` can limit which tool families are exposed to the model
- `memory.enabled`, `memory.user_profile_enabled`, `memory.memory_char_limit`, `memory.user_char_limit` control the memory system; the agent creates a `MemoryStore` if either `enabled` flag is true
- `model.fallback_provider` and `model.fallback_model` configure the one-step provider fallback route
- `SOUL.md` does not currently have config knobs; it is a first-run home-level file rather than a config-driven feature

### LLM Integration

- Uses the `openai` Python SDK with `stream=True`
- Tokens stream through an optional caller-provided callback, with stdout fallback
- Tool calls are accumulated silently, then dispatched after the streamed response finishes
- OpenAI and OpenRouter are both treated as OpenAI-compatible providers
- `astra_claw/llm.py` centralizes provider base URLs, API key lookup, route resolution, and transient-error classification
- The agent tries the primary provider/model first, then retries once on the configured fallback provider/model when the primary fails before meaningful streamed output
- Fallback only applies to transient/runtime failures such as timeouts, connection errors, 429s, and 5xx responses. Auth and malformed-request failures do not fail over.

## File Dependency Chain

```text
constants.py       (no deps)
config.py          (imports constants, soul)
llm.py             (imports OpenAI SDK only)
session.py         (imports constants)
memory.py          (imports constants)
soul.py            (imports constants)
tools/registry.py  (no deps)
tools/*.py         (import registry; memory_tool also imports memory)
agent/loop.py      (imports config, llm, memory, prompt_builder, registry)
cli/*.py           (imports constants, session, Rich, prompt_toolkit)
__main__.py        (imports loop + cli + session)
```

## Tech Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Language | Python 3.11+ | Best LLM SDK support |
| LLM SDK | `openai` | Works with OpenAI + OpenRouter through one client |
| Config | PyYAML | Simple and human-readable |
| CLI input | `prompt_toolkit` | History, completion, and better prompt behavior |
| CLI output | Rich | Lightweight panels/tables/colors |
| Tool calling | OpenAI function calling format | Standard schema format |
| Sessions | JSONL files | Zero deps and easy debugging |
| User data | `~/.astraclaw/` | Kept outside the repo |

## Supported Providers

| Provider | Base URL | Env Var |
|----------|----------|---------|
| OpenAI | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| OpenRouter | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` |

## Testing Strategy

- `tests/test_features.py` covers core regressions for constants, config, registry behavior, and prompt assembly
- `tests/test_session.py` covers JSONL session persistence and recovery behavior
- `tests/test_memory.py` covers `MemoryStore` add/replace/remove, char limits, threat scanning, and frozen-snapshot stability
- `tests/test_soul.py` covers first-run seeding, no-overwrite behavior, loading, fallback, threat blocking, and truncation
- `tests/test_workspace.py` covers the `--workspace` flag and the write fence (inside-ok, relative escape blocked, absolute escape blocked, no-fence fallback, flag parsing, bad path exit)
- `tests/tools/test_patch_tool.py` covers exact replacement, deletion, no-match, multi-match, `replace_all`, protected paths, workspace escapes, and schema registration
- `tests/agent/test_loop.py` also covers primary success, transient fallback success, and no-fallback cases for bad requests
- `tests/cli/` covers slash commands, completion, REPL routing, session switching, and stream callback use
- `tests/tools/` contains module-level tests for file tools, shell execution, search behavior, and the memory tool wrapper
- `tests/agent/` contains mocked loop tests for streaming and tool-call orchestration without live API calls
- The full suite is run with `python -m pytest tests -v`
- Focused commands and suite layout live in `docs/testing.md`
