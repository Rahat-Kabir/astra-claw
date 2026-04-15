# Astra-Claw - Development Guide

Instructions for AI coding assistants and developers working on the astra-claw codebase.
Treat this file like `CLAUDE.md`: it is the project guide for assistant behavior and development rules.

## Core Principles

- **Think Before Coding**: State assumptions. If uncertain, ask. Don't guess.
- **Simplicity First**: No overengineering. No "flexibility" that wasn't asked for.
- **Surgical Changes**: Only touch what is necessary. Don't reformat adjacent code.
- **Goal-Driven**: Create verifiable success criteria (e.g., "Write a test script for X, then make it pass").

## Code Quality

- **Fail Fast**: Do not swallow exceptions. Prefer crashing with a clear stack trace over silent failure. Only catch errors if you have a specific recovery plan.
- **Senior Engineer Test**: Before writing, ask: "Would a senior engineer delete this?" If yes, simplify.
- **Clean Up Orphans**: If you remove a function or variable, you MUST remove its unused imports and dependencies.

## Global

- After adding a new file, tool, or feature, update `README.md` and the Project Structure section in this file to reflect the change.
- After code, update `docs/tech_spec.md` and `docs/progress.md` with the decisions made in the session shortly also `docs/testing.md` if any

## Workflow

- **CLI First**: Every new feature should test in CLI first before UI. Create `scripts/` or `tests/` using Python when needed.
- **Visual Debugging**: If a UI issue is complex, ask for a screenshot.

```bash
# ALWAYS activate before running Python

.\venv\Scripts\Activate.ps1  # Windows PowerShell
# or
source venv/bin/activate     # Git Bash / WSL
```

## Project Structure

```text
astra-claw/
|-- astra_claw/
|   |-- __main__.py           # entry: python -m astra_claw (interactive, one-shot, --session, --sessions, --workspace)
|   |-- constants.py          # get_astraclaw_home() + get_workspace_fence() - single source of truth
|   |-- config.py             # DEFAULT_CONFIG + deep merge + ensure home
|   |-- llm.py                # provider routing, client creation, and transient fallback policy
|   |-- session.py            # JSONL session persistence (create, save, load, list)
|   |-- memory.py             # MemoryStore: frozen-snapshot persistent memory (MEMORY.md + USER.md)
|   |-- soul.py               # SOUL.md loader + first-run seeding for global agent identity
|   |-- cli/
|   |   |-- commands.py       # slash commands + prompt completion
|   |   |-- repl.py           # prompt_toolkit interactive session loop
|   |   `-- ui.py             # Rich banner/help/session/error rendering
|   |-- agent/
|   |   |-- loop.py           # AstraAgent class + run_conversation() -> streaming callback + tool loop
|   |   `-- prompt_builder.py # system prompt assembly (SOUL.md + memory snapshot)
|   `-- tools/
|       |-- registry.py       # register(), get_definitions(), dispatch()
|       |-- path_safety.py    # shared write fence, protected path, and atomic write helpers
|       |-- file_tools.py     # read_file, write_file (with blocked-path safety)
|       |-- patch_tool.py     # patch - exact text replacement with diff output
|       |-- shell_tool.py     # shell command execution (with dangerous command approval)
|       |-- search_tool.py    # search_files - content grep + filename find (cross-platform)
|       `-- memory_tool.py    # memory tool - schema + JSON wrapper over MemoryStore
|-- tests/
|   |-- agent/               # mocked agent loop tests
|   |-- cli/                 # CLI command/completion/REPL tests
|   |-- tools/               # tool-level tests (includes test_memory_tool.py)
|   |-- test_features.py     # core regression tests
|   |-- test_session.py      # session persistence tests
|   |-- test_soul.py         # SOUL.md seeding / loading / fallback tests
|   |-- test_workspace.py    # --workspace flag + write_file fence tests
|   `-- test_memory.py       # MemoryStore tests
|-- docs/
|   |-- tech_spec.md         # technical design notes
|   |-- progress.md          # implementation progress log
|   `-- testing.md           # test commands and suite layout
|-- pyproject.toml
`-- .env.example
```

**User data:** `~/.astraclaw/` (config, sessions, memory, skills - never in repo)

## File Dependency Chain

```text
constants.py       (no deps)
config.py          (imports constants)
llm.py             (imports OpenAI SDK only)
session.py         (imports constants)
tools/registry.py  (no deps)
tools/*.py         (import registry)
agent/loop.py      (imports config, llm, memory, prompt_builder, registry)
cli/*.py           (imports constants, session, Rich, prompt_toolkit)
__main__.py        (imports loop + cli + session)
```

## Rules

- NEVER hardcode `~/.astraclaw` - use `get_astraclaw_home()` from `constants.py`.
- All tool handlers MUST return a JSON string.
- New tool = new file in `tools/` + `registry.register(name=..., toolset=..., ...)` at the bottom.
- Use `patch` for targeted edits to existing files; use `write_file` for new files or deliberate full rewrites.
- Tools may optionally provide a `check_fn` so unavailable tools are hidden from model schemas.
- Tests must NEVER write to `~/.astraclaw/` - set `ASTRACLAW_HOME` env var to `tmp_path`.
- Sessions are JSONL files in `~/.astraclaw/sessions/` - first line is meta, rest are messages.
- `SOUL.md` lives at `~/.astraclaw/SOUL.md`, is seeded on first run if missing, and acts as slot #1 of the system prompt when non-empty.
- `run_conversation()` returns `(text, new_messages)` - session saving happens in `__main__.py`, not in the agent.
- `run_conversation()` accepts optional `stream_writer`; CLI/TUI output should use that instead of adding UI code inside the agent loop.
- Memory lives in `~/.astraclaw/memory/` (`MEMORY.md` + `USER.md`), entries delimited by `§`, char-limited.
- The `memory` tool is special-cased in `agent/loop.py` so the agent's `MemoryStore` is passed to the handler; the registry contract stays uniform (standalone dispatch returns an unavailable-error JSON).
- Memory content is scanned for prompt-injection / exfiltration / invisible-unicode payloads before being persisted, because entries are injected into the system prompt.
- Memory uses a frozen-snapshot pattern: `load_from_disk()` runs once at agent init, and the system prompt never changes mid-session even after writes. Snapshot refreshes on next session start.
- `SOUL.md` content is scanned for prompt-injection / invisible-unicode payloads and truncated before loading; missing, empty, or unreadable files fall back to `DEFAULT_IDENTITY`.
- LLM provider fallback is single-step only: retry once on the configured fallback provider/model for transient errors (timeouts, connection errors, 429, 5xx). Do not fail over on auth or bad-request errors.
- Workspace fence: `--workspace <path>` in `__main__.py` chdirs + sets `_workspace_fence` via `set_workspace_fence()`. `write_file` and `patch` reject any resolved path outside `get_workspace_fence()`. Fence is unset by default (falls back to cwd). Shell + read_file are intentionally NOT fenced.

## Must Follow

- **Take permission** before editing.
