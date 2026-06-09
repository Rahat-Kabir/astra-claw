# Astra-Claw v0.3 — Delegation / Sub-agents

Release Date: 2026-06-10
Covers: v0.3.0

## Summary

v0.1 built the brain; v0.2 built the face and a long tail of CLI/session UX. v0.3 opens the delegation chapter: a parent agent can now hand a context-heavy, self-contained subtask to an isolated child agent and get back only a summary. The child reads files, runs searches, or does web research in its own context — and none of that intermediate tool output ever lands in the parent's context window. The win is isolation, not speed: one sequential child on the same model collapses a large pile of reading into a short report.

## Highlights

- **`delegate` tool** — spawns one fresh `AstraAgent` per call (blocking, depth 1). The child gets a focused system prompt built from `goal` + `context`, no parent history, no SOUL.md, and no memory snapshot. Its final message returns to the parent as a JSON summary (`status`, `exit_reason`, `summary`, `turns`, `duration_seconds`, `child_session_id`). *(v0.3.0)*

- **Recursion-proof by construction** — the child's toolset subtracts the blocked set (`delegation`/`clarify`/`memory`/`planning`/`session_search`), so the child never even sees the `delegate` schema. No depth counter, no grandchildren.

- **`system_prompt_override` on `AstraAgent`** — a child replaces the assembled SOUL.md + memory prompt with its briefing through one clean constructor seam, reusing the entire existing loop (streaming, tool dispatch, compaction) unchanged.

- **Child runs are debuggable** — each delegation is saved as its own JSONL session with `parent_id` in the meta line and a `[delegate] <goal>` title, so you can open the child's full transcript after the fact.

- **Real end-to-end smoke** — `scripts/smoke_delegate.py` runs a live delegation against the configured model, printing the child's tool activity, the summary JSON, and (optionally) the saved transcript.

## Test suite

408 → 424 tests (+16 during v0.3)

- v0.3.0: +16 (`tests/tools/test_delegate_tool.py`), all with a `FakeChildAgent` — no live LLM calls

## Why these changes mattered

- Delegation is the architectural capstone: tools → memory → skills → compaction → delegation completes the arc, and it reuses every prior layer instead of bolting on a parallel system.
- The loop split done back in v0.2.0 paid off here — a child is just another `AstraAgent` with a different system prompt and config; no special agent class was needed.
- The smoke test earned its keep immediately: 16 green unit tests all passed while the *real* behavior was broken. Against gpt-4o-mini, the first child briefing was too weak and children hallucinated tool use — claiming to have read files without ever calling `read_file`. A side-by-side run proved the normal agent fired tools 5/5 on the same model while the child managed 0/2; restoring the "actually call the tool, don't describe" imperative brought the child to 5/5. The fix was one sentence of prompt wording, and it is now locked in with a regression assertion. Lesson worth keeping: mocked tests prove plumbing, real runs prove behavior.

## Deliberately cut from the original plan

- Named-skill children — the child inherits the parent's model route instead.
- Context budget allocation — the child reuses the parent's compaction config for free.
- Parallel / batch children — sequential single-child only; threading is unsafe against JSONL writes and the Rich UI.

## What's next

- Dogfood delegation for real tasks and collect friction (does the parent write good briefings? does it over-delegate small jobs?).
- Older backlog still open: gateway (Telegram/Discord), cron scheduling, skills install flow.

## Reference

Detailed per-version entries live in [docs/progress.md](progress.md) under v0.3.0.
