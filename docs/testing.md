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
python -m pytest tests/test_session.py -v
python -m pytest tests/tools/test_file_tools.py -v
python -m pytest tests/tools/test_shell_tool.py -v
python -m pytest tests/tools/test_search_tool.py -v
python -m pytest tests/agent/test_loop.py -v
```

## Test Layout

- `tests/test_features.py`: core regression tests for constants, config, registry, and prompt builder
- `tests/test_session.py`: JSONL session persistence tests
- `tests/tools/`: tool-level tests for file, shell, and search behavior
- `tests/agent/`: mocked agent loop tests without real provider calls

## Notes

- Unit tests should not call live provider APIs
- Tests that touch user data paths should use a temporary `ASTRACLAW_HOME`
- Prefer adding focused module tests instead of growing one large catch-all file
