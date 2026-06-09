# Testing

## Purpose

The test suite protects the core agent loop, tool handlers, session persistence, and prompt/config regressions without requiring live API calls.

## Run All Tests

```bash
python -m pytest tests -v
```

## Run Focused Tests

```bash
python -m pytest tests/test_features.py -v
python -m pytest tests/test_soul.py tests/test_features.py -v
python -m pytest tests/agent/test_loop.py tests/test_features.py -v
python -m pytest tests/agent/test_context_compactor.py -v
python -m pytest tests/agent/test_context_compactor.py tests/agent/test_loop.py tests/cli/test_repl.py tests/test_session.py -v
python -m pytest tests/cli tests/agent -v
python -m pytest tests/cli -v
python -m pytest tests/cli/test_history_edit.py tests/cli/test_repl.py::test_retry_rewrites_session_and_reruns_last_user_message -v
python -m pytest tests/cli/test_ui_markdown.py tests/cli/test_repl.py::test_markdown_mode_renders_assistant_reply_without_raw_stars -v
python -m pytest tests/cli/test_usage.py tests/cli/test_repl.py::test_usage_command_does_not_call_agent -v
python -m pytest tests/cli/test_model_command.py -v
python -m pytest tests/tools/test_write_approval.py -v
python -m pytest tests/tools/test_delegate_tool.py -v
python -m pytest tests/cli/test_context_refs.py tests/cli/test_context_completion.py tests/cli/test_repl.py -v
python -m pytest tests/cli/test_skills.py tests/cli/test_repl.py -v
python -m pytest tests/tools/test_skills_tool.py -v
python -m pytest tests/test_session.py -v
python -m pytest tests/tools/test_file_tools.py -v
python -m pytest tests/tools/test_patch_tool.py -v
python -m pytest tests/tools/test_shell_tool.py -v
python -m pytest tests/tools/test_search_tool.py -v
python -m pytest tests/tools/test_web_tools.py -v
python -m pytest tests/agent/test_loop.py -v
python -m pytest tests/agent/test_events.py -v
python -m pytest tests/cli/test_tool_display.py -v
python -m pytest tests/test_session.py tests/tools/test_session_search_tool.py -v
python -m pytest tests/tools/test_web_tools.py tests/cli/test_tool_display.py tests/agent/test_loop.py tests/test_features.py -v
```

## Test Layout

- `tests/test_features.py`: core regression tests for constants, config, registry, and prompt builder
- `tests/test_config.py`: `load_user_config` / `save_user_config` partial-override and merge tests
- `tests/test_llm.py`: `resolve_api_key` precedence and `validate_credentials` success/unauthorized/timeout paths
- `tests/cli/test_setup.py`: setup wizard happy path, section flags, validation rejection, keep-existing-key, custom-model, provider-change key invalidation
- `tests/test_soul.py`: SOUL.md seeding, loading, fallback, and truncation tests
- `tests/agent/test_loop.py`: mocked loop tests, including provider fallback and stream callback behavior
- `tests/agent/test_events.py`: `AgentEvents` hooks (thinking toggle, tool start/complete ordering, back-compat, compaction silence)
- `tests/agent/test_context_compactor.py`: compaction budget, protected window, and summary reuse tests
- `tests/cli/test_history_edit.py`: `/retry` truncation helpers (tool-turn tail, empty history)
- `tests/cli/test_usage.py`: pure `/usage` snapshot builder coverage (empty history, would-compact, breakdown sum)
- `tests/cli/test_model_command.py`: `parse_model_arg` (explicit/bare/malformed) + `set_primary_route` in-place switch
- `tests/tools/test_write_approval.py`: write-approval default-allow, write_file/patch reject (no write) + approve (writes), diff passed to callback, no-trailing-newline diff regression, REPL "always" latch
- `tests/tools/test_delegate_tool.py`: delegate tool with a `FakeChildAgent` (no live LLM) - schema, unavailable-standalone dispatch, summary JSON, briefing contents (incl. anti-hallucination imperative regression), child config (memory off / blocked toolsets / turn clamping / parent not mutated), max-turns salvage, crash handling, child session + `parent_id` meta, event forwarding without `on_thinking`, tool_runner special-casing
- `tests/cli/test_ui_markdown.py`: Markdown buffer/finish behavior and plain-stream trailing newline
- `tests/cli/`: slash command, completion, skill discovery/invocation, context-reference expansion and fuzzy completion, REPL routing, `/usage` snapshot tests, Markdown rendering tests, and tool-display preview/summary tests
- `tests/test_session.py`: JSONL session persistence and JSONL session-search tests
- `tests/tools/`: tool-level tests for file, patch, shell, search, web, memory, skills, and session-search behavior
- `tests/agent/`: mocked agent loop tests without real provider calls

## Notes

- Unit tests should not call live provider APIs
- Tests that touch user data paths should use a temporary `ASTRACLAW_HOME`
- Prefer adding focused module tests instead of growing one large catch-all file
- Compaction regressions should cover both the pure compactor and the session rewrite path
