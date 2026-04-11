# Astra-Claw — Progress

## v0.1.0 — MVP (2026-04-10)

### Completed

- [x] `constants.py` — `get_astraclaw_home()` with env var override
- [x] `config.py` — `ensure_astraclaw_home()`, `DEFAULT_CONFIG`, `load_config()` with deep merge
- [x] `tools/registry.py` — `ToolRegistry` singleton with `register()`, `get_definitions()`, `dispatch()`
- [x] `tools/file_tools.py` — `read_file` + `write_file` tools (with blocked-path safety for .env, .git, .ssh, etc.)
- [x] `agent/prompt_builder.py` — hardcoded identity prompt
- [x] `agent/loop.py` — `AstraAgent` class with tool-calling while loop
- [x] `__main__.py` — interactive mode + one-shot mode
- [x] `pyproject.toml` — package config with `astraclaw` CLI entry point
- [x] `CLAUDE.md` — development guide for AI assistants
- [x] `README.md` — project documentation
- [x] Tested: agent responds to messages, calls `read_file` tool, returns results
- [x] `session.py` — JSONL session persistence (`create_session`, `save_message`, `load_session`, `list_sessions`)
- [x] `loop.py` updated — `run_conversation()` returns `(text, new_messages)` tuple
- [x] `__main__.py` updated — `--session <id>` resume, `--sessions` list, auto-save in interactive mode
- [x] `tests/test_features.py` — 24 unit tests for constants, config, registry, file_tools, prompt_builder
- [x] `tools/shell_tool.py` — `shell` tool with dangerous command detection (13 patterns) + user approval callback
- [x] `.env` loading — `python-dotenv` in `__main__.py`, loads before agent init
- [x] Streaming responses — `stream=True` in API call, live token output via `sys.stdout.write()`

### Not Yet Built

- [ ] Provider fallback (OpenAI → OpenRouter on failure)
- [ ] Memory system (markdown files in `~/.astraclaw/memory/`)
- [ ] `web_search` tool
- [ ] Context compression (summarize old turns)
- [ ] SOUL.md loading (custom persona)
- [ ] Gateway (Telegram, Discord, etc.)
- [ ] Skills system
- [ ] Cron scheduling
