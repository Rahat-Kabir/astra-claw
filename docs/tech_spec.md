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
- Manual or automatic compaction archives the old JSONL, then rewrites the session with the compacted transcript and updated compaction metadata

### Context Compaction

- `agent/context_compactor.py` estimates request size with a simple char-based heuristic over the system prompt, replay history, pending user input, and tool schemas
- Compaction keeps the first protected turns and recent tail, then replaces the middle with one synthetic assistant summary message
- Assistant tool-call messages stay attached to their matching tool results so tool history is not split across the compaction boundary
- Repeated compaction folds the earlier synthetic summary into the next summary instead of stacking many summaries
- If the compacted history is not smaller than the original estimate, the rewrite is discarded
- `agent/loop.py` runs preflight compaction before the main model call and retries once on context-overflow errors after forcing compaction
- Summary-generation calls are internal-only and must not stream tokens to the CLI

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
- Rich is used for light output: startup banner, help, session table, warnings, errors, and the live feedback spinner
- Slash commands (`/help`, `/sessions`, `/new`, `/compact`, `/exit`, `/quit`) are handled locally and are not sent to the LLM
- `agent/loop.py` exposes an optional `stream_writer(token)` callback so the CLI owns token rendering
- When no callback is provided, the agent keeps the old stdout streaming behavior
- `/compact` runs manual compaction, archives the current session, rewrites the transcript, and replaces the REPL's active replay history

### Live Feedback Surface

- `agent/events.py` defines `AgentEvents` (frozen dataclass) with three optional hooks: `on_thinking(active)`, `on_tool_start(call_id, name, args)`, `on_tool_complete(call_id, name, args, result)`
- `run_conversation(..., events=None)` keeps the surface opt-in; any missing hook is a no-op and the agent behaves identically when called without events
- `agent/streaming.py` fires `on_thinking(True)` before each streamed LLM call and `on_thinking(False)` on the first content or tool-call delta; compaction summary streams are called with `on_thinking=None` so the user's spinner only tracks user-facing turns
- `agent/tool_runner.py` brackets every dispatch with `on_tool_start` / `on_tool_complete` and preserves the `memory` tool special-case that injects the agent's `MemoryStore`
- `cli/tool_display.py` holds pure preview + summary helpers (no Rich deps): `build_tool_preview` picks the primary arg per tool (path, pattern, command, action+target) and `summarize_tool_result` parses the JSON result into a short human label (line counts, `+N -M` for patch, exit codes for shell, etc.)
- `cli/ui.py` owns the Rich dots spinner via `start_thinking(label)` / `stop_thinking()` and renders one compact dim line per completed tool via `print_tool_line(name, preview, summary)`; errors show in red, no emoji
- `cli/repl.py` builds an `AgentEvents` per turn, updates the spinner label to `Running <tool> <preview>` during dispatch, and wraps `run_conversation` in `try/finally` so the spinner always stops

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
- `build_system_prompt(memory_store, include_memory_hint=None)` layers: SOUL/identity -> `TOOL_POLICY` -> env + shell hint -> optional workspace-fence line (only when `--workspace` is explicitly set) -> memory hint (auto-on when `memory_store` is passed) -> user + memory blocks. `TOOL_POLICY` is a separate layer so SOUL.md cannot drop tool rules.

### Todo / Planning Tool

- Session-scoped `TodoStore` owned by the agent (one per session, not persisted to disk)
- Single `todo` tool: pass `todos` to write, omit to read; every call returns the full list plus `{total, pending, in_progress, completed, cancelled}` summary counts
- `merge=false` (default) replaces the whole list; `merge=true` updates items by id and appends new ones
- Valid statuses: `pending` / `in_progress` / `completed` / `cancelled`; invalid values normalize to `pending`
- Toolset: `planning`, so it can be disabled via `tools.enabled_toolsets` config
- Same special-case pattern as `memory`: `agent/tool_runner.py` routes `fn_name == "todo"` to a handler with the store injected; standalone `registry.dispatch("todo", ...)` returns an unavailable-error JSON
- `TodoStore.format_for_injection()` renders active (pending / in_progress) items; `_maybe_compact_history` in `agent/loop.py` appends that rendering as a synthetic user message after compaction so the plan survives context trimming

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
- `model.context_window` and the `compression.*` keys configure compaction thresholds and protected history windows
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
tools/*.py         (import registry; memory_tool also imports memory; todo_tool is self-contained)
agent/events.py    (no deps)
agent/streaming.py (no agent-local deps; iterates SDK stream + on_thinking)
agent/tool_runner.py (imports memory, tools.memory_tool, tools.todo_tool, tools.registry, events)
agent/loop.py      (imports config, llm, memory, prompt_builder, registry, events, streaming, tool_runner)
cli/tool_display.py (pure helpers; no Rich or prompt_toolkit)
cli/*.py           (imports constants, session, Rich, prompt_toolkit, agent.events, cli.tool_display)
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
- `tests/agent/test_context_compactor.py` covers token estimation, protected windows, summary reuse, and no-benefit compaction rejection
- `tests/cli/` covers slash commands, completion, REPL routing, session switching, and stream callback use
- `tests/tools/` contains module-level tests for file tools, shell execution, search behavior, and the memory tool wrapper
- `tests/agent/` contains mocked loop tests for streaming and tool-call orchestration without live API calls
- `tests/agent/test_events.py` covers `AgentEvents` wiring: thinking toggles, tool start/complete ordering, `events=None` back-compat, and compaction silence
- `tests/cli/test_tool_display.py` covers preview + summary helpers for all 6 tools plus error paths
- The full suite is run with `python -m pytest tests -v`
- Focused commands and suite layout live in `docs/testing.md`
