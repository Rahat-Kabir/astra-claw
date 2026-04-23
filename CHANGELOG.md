# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.6] - 2026-04-22

Initial public release.

### Added
- Terminal CLI with history, slash commands (`/help`, `/sessions`, `/new`, `/compact`, `/exit`), and autocomplete
- Interactive, one-shot, `--session <id>`, and `--sessions` modes
- JSONL session persistence with auto-generated 3-5 word titles
- Tools: `read_file`, `write_file`, `patch`, `shell`, `search_files`, `web_search`, `web_extract`, `session_search`, `todo`, `clarify`, `memory`
- Workspace fence via `--workspace <path>` (scopes `write_file` + `patch` to one directory tree)
- Persistent memory across sessions (`MEMORY.md` + `USER.md`), injected into the system prompt as a frozen snapshot
- Global `SOUL.md` persona file with first-run seeding
- Context compaction - manual `/compact` + automatic preflight
- Live CLI feedback: thinking spinner, one-line tool summaries with line counts / diff deltas / shell exit codes
- OpenAI + OpenRouter providers with single-step transient fallback (timeouts, connection errors, 429, 5xx)
- Dangerous shell commands require interactive approval
- `clarify` tool for ambiguous requests (CLI-only, numbered choices)
- `web_search` and `web_extract` via Tavily (hidden unless `TAVILY_API_KEY` is set)

### Changed
- Tightened `README.md` positioning with explicit audience, safety boundaries, and current limitations
- Expanded `pyproject.toml` package metadata with readme, license, authors, keywords, classifiers, and project URLs

### Security
- Memory content and `SOUL.md` are scanned for prompt-injection and invisible-unicode payloads before being loaded into the prompt
- `write_file` and `patch` reject paths outside the workspace fence and a built-in protected-path blocklist
- Fallback retries only apply to transient errors; auth and bad-request failures never fail over
