# Astra-Claw — Development Guide

Instructions for AI coding assistants and developers working on the astra-claw codebase.

## Core Principles

- **Think Before Coding**: State assumptions. If uncertain, ask. Don't guess.
- **Simplicity First**: No overengineering. No "flexibility" that wasn't asked for.
- **Surgical Changes**: Only touch what is necessary. Don't reformat adjacent code.
- **Goal-Driven**: Create verifiable success criteria (e.g., "Write a test script for X, then make it pass").

## Code Quality

- **Fail Fast**: Do not swallow exceptions. Prefer crashing with a clear stack trace over silent failure. Only catch errors if you have a specific recovery plan.
- **Senior Engineer Test**: Before writing, ask: 'Would a senior engineer delete this?' If yes, simplify.
- **Clean Up Orphans**: If you remove a function or variable, you MUST remove its unused imports and dependencies.

##Global

- After adding a new file, tool, or feature, update README.md and the Project Structure section in this file to reflect the change
- After code, update docs/tech_spec.md and docs/progress.md with the decisions made in the session

## Workflow

- **CLI First**: Every new feature should test in cli first before ui , create scripts/ or test/ using python
- **Visual Debugging**: If a UI issue is complex, ask for a screenshot.

```bash

# ALWAYS activate before running Python

.\venv\Scripts\Activate.ps1  # Windows PowerShell (right now ,I'm using Windows powershell)
# or
source venv/bin/activate     # Git Bash / WSL

```

## Project Structure

```
astra-claw/
├── astra_claw/
│   ├── __main__.py           # entry: python -m astra_claw (interactive, one-shot, --session, --sessions)
│   ├── constants.py          # get_astra_home() — single source of truth
│   ├── config.py             # DEFAULT_CONFIG + deep merge + ensure home
│   ├── session.py            # JSONL session persistence (create, save, load, list)
│   ├── agent/
│   │   ├── loop.py           # AstraAgent class + run_conversation() → streaming + tool loop
│   │   └── prompt_builder.py # system prompt assembly
│   └── tools/
│       ├── registry.py       # register(), get_definitions(), dispatch()
│       ├── file_tools.py     # read_file, write_file (with blocked-path safety)
│       ├── shell_tool.py     # shell command execution (with dangerous command approval)
│       └── search_tool.py    # search_files — content grep + filename find (cross-platform)
├── tests/
│   └── test_features.py      # unit tests (pytest)
├── pyproject.toml
└── .env.example
```

**User data:** `~/.astraclaw/` (config, sessions, memory, skills — never in repo)

## File Dependency Chain

```
constants.py       (no deps)
config.py          (imports constants)
session.py         (imports constants)
tools/registry.py  (imports constants — independent of config)
tools/*.py         (import registry)
agent/loop.py      (imports ALL of the above)
__main__.py        (imports loop + session)
```

## Rules

- NEVER hardcode `~/.astraclaw` — use `get_astra_home()` from `constants.py`
- All tool handlers MUST return a JSON string
- New tool = new file in `tools/` + `registry.register()` at bottom
- Tests must NEVER write to ~/.astraclaw/ — set ASTRACLAW_HOME env var to tmp_path
- Sessions are JSONL files in `~/.astraclaw/sessions/` — first line is meta, rest are messages
- `run_conversation()` returns `(text, new_messages)` — session saving happens in `__main__.py`, not in the agent

## Must follow

- **Take permission** before editing take my permission
