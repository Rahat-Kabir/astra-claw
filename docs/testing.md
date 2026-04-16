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
python -m pytest tests/test_session.py -v
python -m pytest tests/tools/test_file_tools.py -v
python -m pytest tests/tools/test_patch_tool.py -v
python -m pytest tests/tools/test_shell_tool.py -v
python -m pytest tests/tools/test_search_tool.py -v
python -m pytest tests/agent/test_loop.py -v
```

## Test Layout

- `tests/test_features.py`: core regression tests for constants, config, registry, and prompt builder
- `tests/test_soul.py`: SOUL.md seeding, loading, fallback, and truncation tests
- `tests/agent/test_loop.py`: mocked loop tests, including provider fallback and stream callback behavior
- `tests/agent/test_context_compactor.py`: compaction budget, protected window, and summary reuse tests
- `tests/cli/`: slash command, completion, and REPL routing tests
- `tests/test_session.py`: JSONL session persistence tests
- `tests/tools/`: tool-level tests for file, patch, shell, search, and memory behavior
- `tests/agent/`: mocked agent loop tests without real provider calls

## Notes

- Unit tests should not call live provider APIs
- Tests that touch user data paths should use a temporary `ASTRACLAW_HOME`
- Prefer adding focused module tests instead of growing one large catch-all file
- Compaction regressions should cover both the pure compactor and the session rewrite path
