# Astra-Claw - Progress

## v0.1.0 - MVP (2026-04-10)

### Completed

- [x] `constants.py` - `get_astraclaw_home()` with env var override
- [x] `config.py` - `ensure_astraclaw_home()`, `DEFAULT_CONFIG`, `load_config()` with deep merge
- [x] `tools/registry.py` - `ToolRegistry` singleton with `register()`, `get_definitions()`, `dispatch()`
- [x] `tools/file_tools.py` - `read_file` + `write_file` tools with blocked-path safety
- [x] `agent/prompt_builder.py` - hardcoded identity prompt
- [x] `agent/loop.py` - `AstraAgent` class with tool-calling while loop
- [x] `__main__.py` - interactive mode + one-shot mode
- [x] `pyproject.toml` - package config with `astraclaw` CLI entry point
- [x] `CLAUDE.md` - development guide for AI assistants
- [x] `README.md` - project documentation
- [x] `session.py` - JSONL session persistence (`create_session`, `save_message`, `load_session`, `list_sessions`)
- [x] `loop.py` updated - `run_conversation()` returns `(text, new_messages)`
- [x] `__main__.py` updated - `--session <id>` resume, `--sessions` list, auto-save in interactive mode
- [x] `tools/shell_tool.py` - `shell` tool with dangerous command detection and user approval callback
- [x] `.env` loading - `python-dotenv` in `__main__.py`, loaded before agent init
- [x] Streaming responses - `stream=True` in the API call, live token output via `sys.stdout.write()`
- [x] `tools/search_tool.py` - `search_files` tool (content grep + filename find, cross-platform, capped at 50 results)

## v0.1.1 - Registry Foundation Pass (2026-04-11)

### Completed

- [x] `tools/registry.py` upgraded to support `toolset` metadata and optional `check_fn`
- [x] `registry.get_definitions(enabled_toolsets=...)` now filters schemas by toolset and availability
- [x] Built-in tools grouped into `filesystem` and `terminal` toolsets
- [x] `agent/loop.py` now reads optional `tools.enabled_toolsets` from config
- [x] `agent/prompt_builder.py` now describes Windows shell behavior as `cmd`-compatible `shell=True` semantics
- [x] `tests/test_features.py` expanded from 24 to 29 unit tests
- [x] Verified with `python -m pytest tests/test_features.py -v` -> 29 passed

### Not Yet Built

- [ ] Provider fallback (OpenAI -> OpenRouter on failure)
- [ ] Memory system (markdown files in `~/.astraclaw/memory/`)
- [ ] `web_search` tool
- [ ] Context compression (summarize old turns)
- [ ] SOUL.md loading (custom persona)
- [ ] Gateway (Telegram, Discord, etc.)
- [ ] Skills system
- [ ] Cron scheduling

## v0.1.2 - Core Test Coverage Pass (2026-04-11)

### Completed

- [x] Added focused test modules for file tools, session persistence, shell execution, search behavior, and mocked agent loop flows
- [x] Verified module-level runs for each new test file
- [x] Verified the combined suite with `python -m pytest tests -v` -> 60 passed
- [x] Added `docs/testing.md` with minimal test commands and suite layout
