# Astra-Claw - Technical Specification

## Architecture

```text
User Input
    |
__main__.py (parse args, create agent)
    |
AstraAgent.run_conversation()
    |
System Prompt (prompt_builder.py)
    |
LLM API Call (OpenAI SDK)
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
  - `filesystem`: `read_file`, `write_file`, `search_files`
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

### File Tools Safety

- `write_file` blocks writes to sensitive paths such as `.env`, `.git`, `.ssh`, and credential-like filenames
- Blocked patterns are checked against the resolved path parts

### Config: Defaults + User Overrides

- `DEFAULT_CONFIG` lives in `config.py`
- User overrides are loaded from `~/.astraclaw/config.yaml`
- Nested dictionaries are deep-merged
- Optional `tools.enabled_toolsets` can limit which tool families are exposed to the model
- `memory.enabled`, `memory.user_profile_enabled`, `memory.memory_char_limit`, `memory.user_char_limit` control the memory system; the agent creates a `MemoryStore` if either `enabled` flag is true

### LLM Integration

- Uses the `openai` Python SDK with `stream=True`
- Tokens stream directly to stdout
- Tool calls are accumulated silently, then dispatched after the streamed response finishes
- OpenAI and OpenRouter are both treated as OpenAI-compatible providers

## File Dependency Chain

```text
constants.py       (no deps)
config.py          (imports constants)
session.py         (imports constants)
memory.py          (imports constants)
tools/registry.py  (no deps)
tools/*.py         (import registry; memory_tool also imports memory)
agent/loop.py      (imports all of the above)
__main__.py        (imports loop + session)
```

## Tech Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Language | Python 3.11+ | Best LLM SDK support |
| LLM SDK | `openai` | Works with OpenAI + OpenRouter through one client |
| Config | PyYAML | Simple and human-readable |
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
- `tests/tools/` contains module-level tests for file tools, shell execution, search behavior, and the memory tool wrapper
- `tests/agent/` contains mocked loop tests for streaming and tool-call orchestration without live API calls
- The full suite is run with `python -m pytest tests -v`
- Focused commands and suite layout live in `docs/testing.md`
