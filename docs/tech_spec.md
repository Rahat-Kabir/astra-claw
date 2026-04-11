# Astra-Claw — Technical Specification

## Architecture

```
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
Tool Calls? --> registry.dispatch() --> Append Results --> Loop back to LLM
    | (no tools)
Final Response
```

## Core Design Decisions

### Session Persistence (JSONL)
- Each session = one `.jsonl` file in `~/.astraclaw/sessions/`
- First line is metadata (`{"type": "meta", "id": "...", "created": "..."}`)
- Every subsequent line is a message (`user`, `assistant`, or `tool`) with auto-added `ts`
- On load, `ts` is stripped before feeding messages back to the LLM
- Chose JSONL over SQLite: zero deps, human-readable, easy to debug
- SQLite upgrade path: when we need cross-session search or multi-user support

### Single Source of Truth for Paths
- `constants.py` → `get_astraclaw_home()` returns `~/.astraclaw/`
- Overridable via `ASTRACLAW_HOME` env var
- Every module imports this — never hardcode paths

### Repo Code vs User Data Separation
- Code lives in `astra-claw/astra_claw/` (repo, versioned)
- User data lives in `~/.astraclaw/` (auto-created, survives updates)
- Pattern learned from Hermes Agent's `get_hermes_home()`

### Search Tool
- Two modes: `target="content"` (grep/findstr) and `target="files"` (find/dir)
- Cross-platform: auto-detects Windows vs Unix commands
- Results capped at 50 to keep LLM context manageable

### Shell Tool Safety
- 13 regex patterns detect dangerous commands (rm -r, chmod 777, SQL DROP, curl|sh, etc.)
- `set_approval_callback()` lets `__main__.py` inject a user prompt for approval
- No callback registered = dangerous commands blocked outright
- Safe commands run directly via `subprocess.run()` with 30s default timeout

### File Tools Safety
- `write_file` blocks writes to sensitive paths (`.env`, `.git`, `.ssh`, credentials, etc.)
- Blocked patterns checked against full resolved path parts

### Tool Registry Pattern
- Singleton `ToolRegistry` in `tools/registry.py`
- Tools self-register at import time via `registry.register()`
- 3 methods: `register()`, `get_definitions()`, `dispatch()`
- Adding a new tool = new file + register call. Zero changes to existing code.

### Config: Defaults + User Overrides
- `DEFAULT_CONFIG` dict hardcoded in `config.py`
- User overrides in `~/.astraclaw/config.yaml`
- Deep merged at load time — user only specifies what they changed

### LLM Integration
- Uses `openai` Python SDK for all providers with `stream=True`
- Tokens print live via `sys.stdout.write()` + flush; tool calls accumulate silently
- OpenAI and OpenRouter both use OpenAI-compatible API
- Provider base URLs mapped in `agent/loop.py`
- API keys: `load_dotenv()` in `__main__.py` loads `.env` file, then `loop.py` reads via `os.getenv()`

## File Dependency Chain

```
constants.py       (no deps)
config.py          (imports constants)
session.py         (imports constants)
tools/registry.py  (no deps)
tools/*.py         (import registry)
agent/loop.py      (imports all of the above)
__main__.py        (imports loop + session)
```

## Tech Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Language | Python 3.11+ | Best LLM SDK support |
| LLM SDK | `openai` | Works with OpenAI + OpenRouter — one interface |
| Config | PyYAML | Simple, human-readable |
| Tool calling | OpenAI function calling format | Industry standard |
| Sessions | JSONL files | Zero deps, human-readable, debuggable |
| User data | `~/.astraclaw/` | Separated from repo |

## Supported Providers

| Provider | Base URL | Env Var |
|----------|----------|---------|
| OpenAI | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| OpenRouter | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` |
