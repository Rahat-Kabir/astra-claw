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

## v0.2.5 - Session Search (2026-04-21)

Why: give the agent cross-session recall without changing the JSONL storage model yet.

### Completed

- [x] `astra_claw/session.py` - added `list_recent_sessions()` and `search_sessions()` with two-pass JSONL rerank, title/body/tool scoring, snippets, previews, and current-session exclusion
- [x] `astra_claw/tools/session_search_tool.py` - `SESSION_SEARCH_SCHEMA` + thin JSON wrapper, toolset `session_search`
- [x] `astra_claw/agent/tool_runner.py` - `session_search` branch injects `current_session_id` for exclusion
- [x] `astra_claw/agent/loop.py` - `run_conversation()` gains `current_session_id`; imports session search module for registry side-effect
- [x] `astra_claw/cli/repl.py` - passes the active session id into the agent call
- [x] `astra_claw/agent/prompt_builder.py` - tool policy now points the model to `session_search` for cross-session recall
- [x] `astra_claw/cli/tool_display.py` - session-search preview (`query` or `recent sessions`) and summary (`N sessions`)
- [x] `tests/test_session.py` - added recent/search ranking, exclusion, snippet, role-filter, and bad-JSON coverage
- [x] `tests/tools/test_session_search_tool.py` - schema + wrapper coverage
- [x] `tests/agent/test_tool_runner_clarify.py` / `tests/agent/test_loop.py` / `tests/cli/test_repl.py` / `tests/cli/test_tool_display.py` - added plumbing coverage for current-session threading and CLI feedback
- [x] Verified focused suite: `D:\PROJECT\astra-claw\venv\Scripts\python.exe -m pytest tests/test_session.py tests/tools/test_session_search_tool.py tests/agent/test_tool_runner_clarify.py tests/agent/test_loop.py tests/cli/test_repl.py tests/cli/test_tool_display.py -q` -> 88 passed
- [x] Verified full suite: `D:\PROJECT\astra-claw\venv\Scripts\python.exe -m pytest tests -q` -> 256 passed

## v0.2.6 - Tavily Web Tools (2026-04-22)

Why: give the agent live web lookup and page extraction without adding a larger multi-backend stack.

### Completed

- [x] `astra_claw/tools/web_tools.py` - added Tavily-backed `web_search` and `web_extract`, toolset `web`, `check_fn` gating on `TAVILY_API_KEY`
- [x] `astra_claw/agent/loop.py` - imports web tools for registry side-effect
- [x] `astra_claw/agent/prompt_builder.py` - tool policy now points the model to `web_search` and `web_extract`
- [x] `astra_claw/cli/tool_display.py` - added web preview/summary lines
- [x] `astra_claw/constants.py` - fixed `get_astraclaw_home()` to avoid eager `Path.home()` evaluation when `ASTRACLAW_HOME` is set
- [x] `tests/tools/test_web_tools.py` - added focused web tool coverage
- [x] `tests/test_features.py` - added regression coverage for the lazy home-path fix
- [x] User-verified focused pytest runs passed after the constants fix

## v0.2.7 - Setup Wizard + First-Run Onboarding (2026-04-27)

Why: make `pip install astra-claw` usable for public PyPI users without hand-editing yaml. New users hit a wizard, not a stack trace.

### Completed

- [x] `astra_claw/cli/setup.py` - three-step interactive wizard (provider, key, model) with section flags (`provider`, `key`, `model`), curated model lists for OpenAI and OpenRouter, custom-model escape hatch, keep-existing-key path, provider-change key invalidation, non-TTY guard
- [x] `astra_claw/llm.py` - `resolve_api_key()` resolves yaml first then env; `validate_credentials()` pings `/models` with a 5s timeout; `create_client()` and `complete_once()` accept an optional `api_key` argument
- [x] `astra_claw/config.py` - `load_user_config()` reads raw overrides; `save_user_config()` atomically merges partial config into `~/.astraclaw/config.yaml` (only changed keys; defaults stay implicit)
- [x] `astra_claw/agent/loop.py` - `AstraAgent` now reads `model.api_key` from yaml when creating clients; exposes `model_config` for downstream callers
- [x] `astra_claw/agent/title_generator.py` - threads `api_key` through to `complete_once` so auto-titles work when the key lives in yaml only
- [x] `astra_claw/cli/repl.py` - resolves and passes the api key into `maybe_auto_title`
- [x] `astra_claw/__main__.py` - subcommand router (`astraclaw setup [section]`) and first-run guard that auto-prompts the wizard in chat mode when no key is reachable
- [x] `tests/cli/test_setup.py` - 7 tests covering full wizard, section flags, key validation, keep-existing-key, custom-model path, provider-change key invalidation, and unknown sections
- [x] `tests/test_config.py` - 4 tests covering `save_user_config()` partial overrides, merge-into-existing, defaults overlay, and missing-file behavior
- [x] `tests/test_llm.py` - 8 tests covering `resolve_api_key()` precedence, explicit-key passthrough, missing-key error, and `validate_credentials()` success / unauthorized / timeout / empty-key paths
- [x] Updated existing `tests/agent/test_loop.py` and `tests/agent/test_title_generator.py` for the new `api_key=` signature
- [x] Verified full suite: 291 passed
- [x] Verified end-to-end smoke run: wizard wrote a clean yaml; first-run guard correctly detects missing keys and offers setup

## v0.2.8 - Context References (2026-05-13)

Why: let users attach precise file, folder, diff, and past-session context inline without spending a tool turn.

### Completed

- [x] `astra_claw/cli/context_refs.py` - expands `@file:`, `@file:<path>:<line-range>`, `@folder:`, `@diff`, and `@session:` into an `--- Attached Context ---` block before agent turns
- [x] `astra_claw/cli/repl.py` and `astra_claw/__main__.py` - apply context-reference expansion in interactive and one-shot modes
- [x] `astra_claw/tools/path_safety.py` - exposes shared sensitive-path checks for read attachments while preserving existing write safety
- [x] Output caps, binary-file rejection, current-session rejection, workspace-fence checks, and warning blocks for missing/blocked refs
- [x] `tests/cli/test_context_refs.py` plus REPL plumbing coverage
- [x] Verified focused suite: `python -m pytest tests\cli\test_context_refs.py tests\cli\test_repl.py -q` -> 24 passed
- [x] Verified full suite: `python -m pytest tests -q` -> 305 passed

## v0.2.9 - Heartbeat Spinner (2026-05-14)

Why: long autonomous turns felt frozen - a static "Thinking" spinner gave no signal that the agent was alive, working, or how deep in a tool loop it was.

### Completed

- [x] `astra_claw/cli/ui.py` - heartbeat state on `CliUI` (`_hb_started`, `_hb_tools`, `_hb_tokens`, `_hb_label`) with `_fmt_elapsed` / `_fmt_tokens` helpers
- [x] `start_thinking(label)` starts or resumes preserving counters; new `pause_thinking()` hides the spinner without resetting state so streamed tokens print cleanly; `stop_thinking()` does the full reset at turn end
- [x] `bump_tool()`, `bump_tokens(n)`, `set_heartbeat_label(label)` mutate counters between events; 0.5s daemon-thread tick advances elapsed time during silent gaps
- [x] Render format: `<label> · <N> tools · <elapsed> · ~<tokens> tok` (e.g. `thinking · 4 tools · 1m42s · ~3.2k tok`)
- [x] `astra_claw/cli/repl.py` - `on_thinking(False)` pauses instead of stopping, `on_tool_complete` pauses + bumps tool counter + relabels to `thinking`, `stream_writer` wrapped to call `bump_tokens(len(token) // 4)`
- [x] `tests/cli/test_ui_heartbeat.py` - 15 tests covering formatters, render output, counter bumps, pause/resume state preservation, full reset on stop
- [x] Verified full suite: `python -m pytest -q` -> 329 passed

## v0.2.10 - Lightweight Skills (2026-05-26)

Why: let users store reusable task workflows as markdown and invoke them from the CLI without adding Python code.

### Completed

- [x] `astra_claw/cli/skills.py` - discovers `~/.astraclaw/skills/**/SKILL.md`, parses simple `name` / `description` frontmatter, slugifies names, caps skill file reads, and builds one-turn invocation messages
- [x] `astra_claw/cli/commands.py` / `cli/repl.py` / `cli/ui.py` - added `/skills` listing and `/skill <name> <request>` one-turn skill loading
- [x] `astra_claw/agent/prompt_builder.py` - appends a compact installed-skills index while keeping full skill bodies out of the system prompt until invoked
- [x] `tests/cli/test_skills.py` plus command, REPL, and prompt-builder coverage
- [x] Verified focused suite: `uv run --with pytest pytest tests/cli/test_commands.py tests/cli/test_skills.py tests/cli/test_repl.py tests/test_features.py` -> 58 passed

## v0.2.11 - Skills Agent Tool (2026-05-27)

Why: let the model load full skill instructions on demand instead of relying only on the compact index or user slash commands.

### Completed

- [x] `astra_claw/tools/skills_tool.py` - `skills` tool with `list` and `view` actions; `view` returns raw `SKILL.md`; hidden via `check_fn` when no skills are installed
- [x] `astra_claw/agent/loop.py` - imports the tool module so it registers at agent startup
- [x] `astra_claw/cli/tool_display.py` - preview/summary lines for `skills` tool calls
- [x] `astra_claw/cli/skills.py` - normalize CRLF line endings in frontmatter parsing so Windows `SKILL.md` files parse correctly
- [x] `tests/tools/test_skills_tool.py` plus CRLF coverage in `tests/cli/test_skills.py`
- [x] Verified full suite: `uv run --with pytest pytest -q` -> 351 passed

## v0.2.12 - Context-Ref Fuzzy Picker (2026-05-28)

Why: make `@file:` and `@folder:` easier to use without knowing full paths.

### Completed

- [x] `astra_claw/cli/context_completion.py` - fuzzy workspace search for `@file:` / `@folder:` partials, scoped search under typed directories, session title matching for `@session:`, path size/folder-count preview meta, and a 25-result cap
- [x] `tests/cli/test_context_completion.py` - nested fuzzy match, session title match, and cap coverage
- [x] Verified full suite: `uv run --with pytest pytest -q` -> 355 passed

## v0.2.13 - Smarter Session Titling (2026-05-28)

Why: greeting-only first turns were producing useless `/sessions` titles like "Casual Hello".

### Completed

- [x] `astra_claw/agent/title_generator.py` - `is_low_signal_user_message()` skips greetings/small talk; titles fire on the first substantive exchange instead of only the first two turns; still one title per session, no re-title
- [x] `tests/agent/test_title_generator.py` - greeting skip, later substantive turn, and existing-title guard coverage
- [x] Verified full suite: `uv run --with pytest pytest -q` -> 359 passed

## v0.2.14 - Skill Slash Aliases (2026-05-30)

Why: make installed skills invokable as first-class slash commands instead of only via `/skill <name> <request>`.

### Completed

- [x] `astra_claw/cli/skills.py` - `get_skill_commands()` and `resolve_skill_command()` map each installed skill to `/<slug>`; built-in slash commands win on collisions; `_`/`-` treated interchangeably
- [x] `astra_claw/cli/repl.py` - dispatches skill aliases before agent turns; keeps `/skill` as explicit fallback
- [x] `astra_claw/cli/commands.py` - tab completion includes installed skill aliases
- [x] `tests/cli/test_skills.py`, `tests/cli/test_repl.py`, `tests/cli/test_commands.py` - alias dispatch, collision skip, completion, and underscore alias coverage
- [x] Verified full suite: `uv run --with pytest pytest -q` -> 367 passed

## v0.2.15 - Usage Panel (2026-06-01)

Why: users need visibility into context pressure before auto-compact fires.

### Completed

- [x] `astra_claw/cli/usage.py` - `UsageSnapshot` + pure `build_usage_snapshot()` from agent, history, session meta, and heartbeat counters
- [x] `astra_claw/agent/context_compactor.py` - `estimate_request_breakdown()`, `compaction_threshold_budget()`, and `threshold_budget` property
- [x] `astra_claw/agent/loop.py` - public `get_system_prompt_text()` wrapper for CLI diagnostics
- [x] `astra_claw/cli/ui.py` - `get_heartbeat_snapshot()` + Rich `print_usage_panel()` with context bar, breakdown, compaction status, memory chars, and last-turn stats
- [x] `astra_claw/cli/commands.py` / `cli/repl.py` - `/usage` local slash command (no LLM call)
- [x] `tests/cli/test_usage.py`, `tests/cli/test_repl.py`, `tests/cli/test_commands.py`, `tests/agent/test_context_compactor.py` - snapshot, REPL dispatch, registry, and breakdown coverage

## v0.2.16 - Markdown Rendering (2026-06-01)

Why: assistant replies often use Markdown syntax; plain streaming showed raw `**` and list markers in the terminal.

### Completed

- [x] `astra_claw/config.py` - `cli.render_markdown` default (`false` keeps live token streaming)
- [x] `astra_claw/cli/ui.py` - `begin_assistant_response()`, `finish_assistant_response()`, and `set_render_markdown()`; buffers tokens when enabled, prints Rich `Markdown` after the turn
- [x] `astra_claw/cli/repl.py` / `__main__.py` - read config per turn; interactive and one-shot modes use the same finish path
- [x] Session JSONL still stores raw assistant text; only display changes
- [x] `tests/cli/test_ui_markdown.py` and REPL integration coverage in `tests/cli/test_repl.py`

## v0.2.17 - /retry Command (2026-06-01)

Why: let users redo a bad answer without retyping the prompt.

### Completed

- [x] `astra_claw/cli/history_edit.py` - `find_last_user_message()` + `truncate_for_retry()`
- [x] `astra_claw/cli/commands.py` / `cli/repl.py` - `/retry` truncates JSONL, archives, and re-runs the last user message
- [x] `tests/cli/test_history_edit.py` and REPL integration tests

## v0.2.18 - Banner Model Label (2026-06-07)

Why: show the active primary route at REPL startup without opening config.

### Completed

- [x] `astra_claw/llm.py` - `format_route_label()` returns `provider:model` from a resolved route
- [x] `astra_claw/cli/ui.py` - startup banner adds an optional **Model** row
- [x] `astra_claw/cli/repl.py` - passes `format_route_label(agent.primary_route)` into `print_banner`
- [x] `tests/cli/test_ui_banner.py` - formatter + banner coverage
- [x] Verified: `python -m pytest tests/cli/test_ui_banner.py tests -q` -> 391 passed

## v0.2.19 - /model Command (2026-06-09)

Why: switch model from the REPL without editing config or restarting.

### Completed

- [x] `astra_claw/cli/commands.py` - `/model` command + pure `parse_model_arg()` (`provider:model` or bare `model`)
- [x] `astra_claw/agent/loop.py` - `set_primary_route()` switches route in place and warms the client
- [x] `astra_claw/cli/ui.py` - `print_model_info()` for bare `/model`
- [x] `astra_claw/cli/repl.py` - `/model` branch: validate key (fail fast), switch live, persist via `save_user_config`
- [x] `tests/cli/test_model_command.py` + updated `test_commands.py`
- [x] Verified: `python -m pytest -q` -> 399 passed

## Next

- [ ] Skills polish: optional install flow or richer frontmatter.

## Planned

### v0.3.0 - Delegation / Sub-agents (chapter theme)

Why: once skills exist, sub-agents get real - a parent agent can spawn a child with a different skill. Composition story.

- [ ] `delegate` tool - spawn a child AstraAgent with a named skill, return its final answer
- [ ] Session parent/child linkage in session metadata (storage-agnostic, still JSONL)
- [ ] Context budget allocation between parent and children
- [ ] Tests + smoke script

## Deferred (not scheduled)

- SQLite migration - only when a concrete feature demands it (first firm candidate: gateway, which is not committed)
- Gateway (Telegram / Discord) - defer until committed; pulls cron, SQLite, concurrent writes behind it
- Cron scheduling - depends on gateway or persistent runner
- MCP client - overlaps with skills; pick one extensibility story first
- Prompt caching - only matters at scale
- Analytics / usage dashboard - wait until there's enough data to look at
