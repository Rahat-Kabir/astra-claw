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
- [x] `AGENTS.md` / `CLAUDE.md` style development guide for AI assistants
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

- [ ] `web_search` tool
- [ ] Context compression (summarize old turns)
- [ ] Gateway (Telegram, Discord, etc.)
- [ ] Skills system
- [ ] Cron scheduling

## v0.1.2 - Core Test Coverage Pass (2026-04-11)

### Completed

- [x] Added focused test modules for file tools, session persistence, shell execution, search behavior, and mocked agent loop flows
- [x] Verified module-level runs for each new test file
- [x] Verified the combined suite with `python -m pytest tests -v` -> 60 passed
- [x] Added `docs/testing.md` with minimal test commands and suite layout

## v0.1.3 - Memory System (2026-04-12)

### Completed

- [x] `astra_claw/memory.py` - `MemoryStore` with add/replace/remove, `§`-delimited entries, char limits, atomic writes, frozen system-prompt snapshot
- [x] Content scanning rejects prompt-injection / exfiltration / invisible-unicode payloads before persistence
- [x] `astra_claw/tools/memory_tool.py` - schema + thin JSON wrapper registered in the `memory` toolset
- [x] `astra_claw/agent/loop.py` - creates `MemoryStore` when `memory.enabled` or `memory.user_profile_enabled`, loads snapshot once, special-cases `memory` tool dispatch to inject the store
- [x] `astra_claw/agent/prompt_builder.py` - `build_system_prompt(memory_store, include_memory_hint)` injects user + memory blocks and short behavior hint
- [x] `astra_claw/config.py` - `memory` defaults (enabled flags + char limits)
- [x] `tests/test_memory.py` - 14 `MemoryStore` tests (round-trip, dedup, char limit, threat scanning, frozen snapshot stability, no delimiter corruption)
- [x] `tests/tools/test_memory_tool.py` - 9 wrapper tests (schema, missing store, arg validation, standalone dispatch error)
- [x] Verified new tests: 23/23 passing via `python -m pytest tests/test_memory.py tests/tools/test_memory_tool.py -v`

## v0.1.4 - SOUL.md Identity Layer (2026-04-13)

### Completed

- [x] `astra_claw/soul.py` - `SOUL.md` loader with first-run seeding, prompt-injection scanning, and truncation
- [x] `astra_claw/config.py` - `ensure_astraclaw_home()` now seeds `~/.astraclaw/SOUL.md` when missing
- [x] `astra_claw/agent/prompt_builder.py` - prompt identity now loads from `SOUL.md` first, then falls back to `DEFAULT_IDENTITY`
- [x] `tests/test_soul.py` - focused tests for seeding, no-overwrite behavior, valid loading, fallback, unsafe-content blocking, and truncation
- [x] Verified focused tests: `python -m pytest tests/test_soul.py tests/test_features.py -v` -> 33 passed

## v0.1.5 - Provider Fallback (2026-04-14)

### Completed

- [x] `astra_claw/llm.py` - centralized provider routing, client creation, and transient failover classification
- [x] `astra_claw/config.py` - added `model.fallback_model` alongside `fallback_provider`
- [x] `astra_claw/agent/loop.py` - primary route + one-step fallback retry when the primary fails before meaningful streamed output
- [x] Fallback policy limited to transient/runtime failures (`timeout`, connection errors, `429`, `5xx`); auth and bad-request failures do not fail over
- [x] `tests/agent/test_loop.py` - added focused tests for transient fallback success, bad-request no-fallback, and fallback-client creation failure
- [x] `tests/test_features.py` - added helper tests for route resolution and failover-worthy error classification
- [x] Verified focused tests: `python -m pytest tests/agent/test_loop.py tests/test_features.py -v` -> 34 passed

## v0.1.6 - Workspace Fence (2026-04-14)

### Completed

- [x] `astra_claw/constants.py` - added `_workspace_fence`, `set_workspace_fence()`, `get_workspace_fence()` (falls back to cwd when unset)
- [x] `astra_claw/__main__.py` - `--workspace <path>` flag parsed first, validates + resolves path, `os.chdir()`, sets fence, prints workspace in session banner
- [x] `astra_claw/tools/file_tools.py` - `_inside_fence()` check in `write_file` runs before the blocklist; rejects escapes with `"escapes workspace fence"`
- [x] `read_file` and `shell` intentionally left unfenced (reads are non-destructive, shell cwd inheritance already scopes normal commands)
- [x] `tests/test_workspace.py` - 7 tests (inside-ok, relative-escape-blocked, absolute-escape-blocked, no-fence-fallback, flag-sets-fence, bad-path-exits, flag-absent-noop)
- [x] `tests/tools/test_file_tools.py` - autouse fixture points fence at `tmp_path` so existing write tests still pass
- [x] Verified focused tests: `python -m pytest tests/test_workspace.py tests/tools/test_file_tools.py -v` -> 18 passed

## v0.1.7 - Patch Tool (2026-04-15)

### Completed

- [x] `astra_claw/tools/path_safety.py` - shared write fence, protected path, and atomic write helpers
- [x] `astra_claw/tools/patch_tool.py` - exact text replacement tool with `replace_all` and unified diff output
- [x] `astra_claw/tools/file_tools.py` - `write_file` now uses shared atomic write safety
- [x] `astra_claw/agent/loop.py` - imports `patch_tool` so it self-registers
- [x] `astra_claw/agent/prompt_builder.py` - prompts the agent to prefer `patch` for targeted edits
- [x] `tests/tools/test_patch_tool.py` - 10 focused patch tool tests
- [x] Verified full suite: `python -m pytest tests -v` -> 115 passed

## v0.1.8 - Light TUI + Stream Callback (2026-04-15)

### Completed

- [x] Added `rich` and `prompt-toolkit` dependencies
- [x] Added `astra_claw/cli/` for slash commands, prompt history/completion, Rich banner/help/session output, and REPL routing
- [x] `astra_claw/agent/loop.py` now accepts optional `stream_writer(token)` while keeping stdout fallback
- [x] `astra_claw/__main__.py` now delegates interactive mode to the CLI REPL
- [x] Added `tests/cli/` plus stream callback coverage in agent loop tests
- [x] Verified focused tests: `python -m pytest tests\cli tests\agent -v` -> 20 passed
- [x] Verified full suite: `python -m pytest tests -v` -> 128 passed

## v0.2.0 - Live Feedback UI + Loop Split (2026-04-17)

### Completed

- [x] `astra_claw/agent/events.py` - `AgentEvents` dataclass with three optional hooks: `on_thinking`, `on_tool_start`, `on_tool_complete`
- [x] `astra_claw/agent/streaming.py` - extracted `collect_stream_response` + `is_context_overflow_error` from the loop; fires `on_thinking(True)` before the stream and `on_thinking(False)` on the first content/tool-call delta
- [x] `astra_claw/agent/tool_runner.py` - extracted `execute_tool_calls`; emits tool start/complete events around each dispatch while preserving the `memory` tool special-case
- [x] `astra_claw/agent/loop.py` slimmed from 392 to 284 lines; `run_conversation` gained keyword `events: AgentEvents | None = None`
- [x] `astra_claw/cli/tool_display.py` - pure `build_tool_preview(name, args)` + `summarize_tool_result(name, result)` helpers (no Rich deps)
- [x] `astra_claw/cli/ui.py` - `start_thinking` / `stop_thinking` (Rich dots spinner, dim, no emoji) + `print_tool_line(name, preview, summary)` one-line compact renderer
- [x] `astra_claw/cli/repl.py` - builds `AgentEvents` per turn via `_build_agent_events(cli_ui)`; spinner label updates to `Running <tool> <preview>` during dispatch; `try/finally` guarantees spinner stops
- [x] Compaction summary calls explicitly pass no thinking callback so the user's spinner only tracks user-facing turns
- [x] `tests/agent/test_events.py` - 4 tests (thinking toggles, tool start/complete ordering, `events=None` back-compat, compaction silence)
- [x] `tests/cli/test_tool_display.py` - 18 tests covering preview + summary for all 6 tools plus error paths
- [x] `scripts/smoke_feedback_ui.py` - manual visual smoke test of the feedback surface
- [x] Verified full suite: `python -m pytest tests -q` -> 167 passed

## v0.1.9 - Context Compaction (2026-04-16)

### Completed

- [x] `astra_claw/agent/context_compactor.py` - persistent history compaction with protected head/tail windows, tool-pair preservation, summary reuse, and no-benefit rejection
- [x] `astra_claw/agent/loop.py` - preflight compaction before model calls, one retry on context-overflow errors, and silent internal summary generation
- [x] `astra_claw/session.py` - session metadata loading, archive copy creation, and full transcript rewrite for compacted sessions
- [x] `astra_claw/cli/commands.py` / `cli/repl.py` / `cli/ui.py` - added `/compact`, compaction status output, and active-history replacement after manual or automatic compaction
- [x] `astra_claw/config.py` - added `model.context_window` and `compression.*` defaults
- [x] Added compaction-focused tests for agent, CLI, and session rewrite/archive behavior
- [x] Verified full suite: `.\venv\Scripts\pytest.exe` -> 145 passed

## v0.2.1 - Prompt Layering Fix (2026-04-17)

### Completed

- [x] `astra_claw/agent/prompt_builder.py` - split `TOOL_POLICY` out of `DEFAULT_IDENTITY` so SOUL.md cannot drop tool rules
- [x] `astra_claw/agent/prompt_builder.py` - memory hint auto-enables when `memory_store` is passed (flag now defaults to `None`)
- [x] `astra_claw/agent/prompt_builder.py` - announces workspace fence in the prompt when `--workspace` is explicitly set
- [x] Verified: `python -m pytest tests/test_soul.py tests/test_features.py tests/test_workspace.py` -> 43 passed

## v0.2.2 - Todo / Planning Tool (2026-04-17)

### Completed

- [x] `astra_claw/tools/todo_tool.py` - `TodoStore` + `todo_tool()` + `TODO_SCHEMA`, toolset `planning`
- [x] `astra_claw/agent/tool_runner.py` - special-cases `todo`, injects agent's `TodoStore`
- [x] `astra_claw/agent/loop.py` - creates `self.todo_store` per session, passes it to `execute_tool_calls`, re-injects active items as a synthetic user message after compaction
- [x] `astra_claw/cli/tool_display.py` - todo preview (`read` / `write N items` / `merge N items`) and summary (`X in progress / Y pending`)
- [x] `tests/tools/test_todo_tool.py` + todo cases in `tests/cli/test_tool_display.py`
- [x] Verified full suite: `python -m pytest -q` -> 186 passed (1 pre-existing shell-approval failure unrelated)

## v0.2.3 - Session Title Auto-generation (2026-04-18)

### Completed

- [x] `astra_claw/session.py` - `get_session_title` / `set_session_title`; `list_sessions` now exposes `title`
- [x] `astra_claw/llm.py` - `complete_once()` non-streaming helper; auto-falls back from `max_completion_tokens` to legacy `max_tokens` so it works with both gpt-5.x and older models
- [x] `astra_claw/agent/title_generator.py` - `generate_title` / `auto_title_session` / `maybe_auto_title`; fires on daemon thread after the first 1-2 exchanges, silent-fail on any error
- [x] `astra_claw/config.py` - `session.auto_title: True` default; title model resolves from `compression.summary_model` -> `model.fallback_model` -> `model.default`
- [x] `astra_claw/cli/repl.py` - schedules auto-title after each user-facing turn; joins pending title threads on exit (5s/thread) so daemon threads aren't killed mid-flight
- [x] `astra_claw/cli/ui.py` - `/sessions` gets a Title column; banner shows title on resume
- [x] `scripts/smoke_title.py` - synchronous smoke test with optional `--persist` and `--verbose`
- [x] `tests/agent/test_title_generator.py` + `tests/test_session.py` + `tests/cli/test_repl.py` - 26 new tests
- [x] Verified full suite: `python -m pytest tests -q` -> 212 passed (1 pre-existing shell-approval failure, unrelated)
- [x] Verified end-to-end: session `2026-04-18_bbdd9cbf` auto-titled `"Greeting and Offer to Help"` from a live REPL run

## v0.2.4 - Clarify Tool (2026-04-19)

Why: give the agent a structured way to pause and ask one question instead of guessing on ambiguous requests.

### Completed

- [x] `astra_claw/tools/clarify_tool.py` - `CLARIFY_SCHEMA` + `clarify_tool(question, choices, callback)`, toolset `clarify`; handler is a thin shell that delegates to a platform callback
- [x] `astra_claw/agent/tool_runner.py` - `clarify` branch injects `clarify_callback` (same pattern as `memory` / `todo`)
- [x] `astra_claw/agent/loop.py` - `run_conversation` gains `clarify_callback` kwarg; imports clarify module for registry side-effect
- [x] `astra_claw/cli/repl.py` - `_build_clarify_callback(cli_ui, prompt_session)` stops the spinner, renders the question, reads one line; numeric in-range resolves to choice text, everything else returned verbatim
- [x] `astra_claw/cli/ui.py` - `print_clarify_question` renders question + numbered choices (auto-appends "Other")
- [x] `astra_claw/cli/tool_display.py` - clarify preview (question) and summary (user_response)
- [x] `astra_claw/agent/prompt_builder.py` - one `TOOL_POLICY` line guiding when to use clarify
- [x] `tests/tools/test_clarify_tool.py` - 11 tests (schema, validation, trimming, callback injection, exception wrapping, standalone-registry error)
- [x] `tests/agent/test_tool_runner_clarify.py` - 3 tests (callback threaded, missing-callback error, other tools unaffected)
- [x] `tests/cli/test_repl_clarify.py` - 6 tests (numeric / out-of-range / freetext / open-ended / KeyboardInterrupt / EOF)
- [x] `tests/cli/test_tool_display.py` - 3 clarify cases added
- [x] `tests/cli/test_repl.py` - `FakeAgent.run_conversation` accepts new `clarify_callback` kwarg
- [x] Verified full suite: `python -m pytest tests -q` -> 235 passed (1 pre-existing shell-approval failure, unrelated)

### Out of scope (deferred)

- Arrow-key navigation UI
- Timeout / auto-proceed
- Gateway (Telegram / Discord) wiring

## Next

- [ ] Smarter titling: skip greetings-only first turns; optionally re-title at N=4 exchanges with more context.
