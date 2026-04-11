# Astra-Claw - Development Guide

Instructions for AI coding assistants and developers working on the astra-claw codebase.

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
- After code, update `docs/tech_spec.md` and `docs/progress.md` with the decisions made in the session.

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
|   |-- __main__.py           # entry: python -m astra_claw (interactive, one-shot, --session, --sessions)
|   |-- constants.py          # get_astraclaw_home() - single source of truth
|   |-- config.py             # DEFAULT_CONFIG + deep merge + ensure home
|   |-- session.py            # JSONL session persistence (create, save, load, list)
|   |-- agent/
|   |   |-- loop.py           # AstraAgent class + run_conversation() -> streaming + tool loop
|   |   `-- prompt_builder.py # system prompt assembly
|   `-- tools/
|       |-- registry.py       # register(), get_definitions(), dispatch()
|       |-- file_tools.py     # read_file, write_file (with blocked-path safety)
|       |-- shell_tool.py     # shell command execution (with dangerous command approval)
|       `-- search_tool.py    # search_files - content grep + filename find (cross-platform)
|-- tests/
|   |-- agent/               # mocked agent loop tests
|   |-- tools/               # tool-level tests
|   |-- test_features.py     # core regression tests
|   `-- test_session.py      # session persistence tests
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
session.py         (imports constants)
tools/registry.py  (no deps)
tools/*.py         (import registry)
agent/loop.py      (imports all of the above)
__main__.py        (imports loop + session)
```

## Rules

- NEVER hardcode `~/.astraclaw` - use `get_astraclaw_home()` from `constants.py`.
- All tool handlers MUST return a JSON string.
- New tool = new file in `tools/` + `registry.register(name=..., toolset=..., ...)` at the bottom.
- Tools may optionally provide a `check_fn` so unavailable tools are hidden from model schemas.
- Tests must NEVER write to `~/.astraclaw/` - set `ASTRACLAW_HOME` env var to `tmp_path`.
- Sessions are JSONL files in `~/.astraclaw/sessions/` - first line is meta, rest are messages.
- `run_conversation()` returns `(text, new_messages)` - session saving happens in `__main__.py`, not in the agent.

## Must Follow

- **Take permission** before editing.
