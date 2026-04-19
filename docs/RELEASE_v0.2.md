# Astra-Claw v0.2 — Interactive CLI + Session UX

Release Date: 2026-04-18
Covers: v0.2.0 → v0.2.3

## Summary

v0.1 built the brain — tools, memory, identity (SOUL.md), provider fallback, workspace fence, patch tool, context compaction. v0.2 built the face. Astra-Claw stopped being "a script with tools" and became "an app you sit in front of": a Rich-based REPL with a live thinking spinner, compact one-line tool previews, a session-scoped planning tool, and sessions that auto-title themselves from the first exchange.

## Highlights

- **Live Feedback UI + Loop Split** — `AgentEvents` hook surface (`on_thinking`, `on_tool_start`, `on_tool_complete`), Rich dots spinner during LLM calls, one-line `Running <tool> <preview>` feedback per dispatch. `agent/loop.py` split into `events.py` + `streaming.py` + `tool_runner.py` (392 → 284 lines). *(v0.2.0)*

- **Prompt Layering Fix** — `TOOL_POLICY` split out of `DEFAULT_IDENTITY` so `SOUL.md` can no longer silently drop tool rules. Memory hint auto-enables when a `MemoryStore` is passed. Workspace fence announced in the system prompt when `--workspace` is set. *(v0.2.1)*

- **Todo / Planning Tool** — session-scoped `TodoStore` owned by the agent, `todo` tool in the new `planning` toolset. Active items are re-injected as a synthetic user message after context compaction so the plan survives summarization. *(v0.2.2)*

- **Auto Session Titles** — sessions auto-title themselves from the first 1-2 exchanges on a daemon thread (silent-fail). `/sessions` gained a Title column, banner shows title on resume. New `llm.complete_once()` non-streaming helper with automatic `max_completion_tokens` → `max_tokens` fallback for older models. *(v0.2.3)*

## Test suite

145 → 212 tests (+67 during v0.2)

- v0.2.0: +22 (events + tool_display)
- v0.2.2: +19 (todo tool + CLI preview cases)
- v0.2.3: +26 (title generator + session + repl)

## Why these changes mattered

- The loop split means non-CLI callers (future gateways, tests, subagents) can plug in without importing Rich or prompt_toolkit.
- Tool-call feedback was previously invisible — the agent felt frozen during long tool calls. The spinner + tool line fixed that without touching the agent loop.
- Todo items were being forgotten after compaction; re-injection keeps multi-step plans alive.
- Un-named sessions were hard to find in `/sessions`; auto-titles make history browsable.

## What's next (v0.3 candidates)

- **Clarify tool** — structured way for the agent to pause and ask one clarifying question instead of guessing.
- **Smarter titling** — skip greetings-only first turns; optionally re-title at N=4 exchanges with more context.
- Older backlog still open: `web_search` tool, skills system, gateway (Telegram/Discord), cron scheduling.

## Reference

Detailed per-version entries live in [docs/progress.md](progress.md) under v0.2.0 → v0.2.3.
