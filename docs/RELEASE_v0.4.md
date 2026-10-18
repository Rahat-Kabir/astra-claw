# Astra-Claw v0.4 — Measurement

Release Date: 2026-10-19
Covers: v0.4.0

The measurement chapter starts with request evidence. Each model call records
its route, run identity, timing, outcome, and provider-reported token usage in
local append-only JSONL files. Missing usage stays unknown. Parent IDs link
delegated work and background titles to the originating conversation.

Stream usage-only chunks, fallback attempts, non-streaming compatibility retries,
and compaction calls are covered. Hidden SDK retries are disabled for model
calls so each explicit attempt has a separate record. Existing context estimates
in `/usage` are unchanged.

Validation uses mocked model responses, failures, interrupts, and thread/delegate
checks. No live provider run or billing reconciliation is claimed.

Cost calculation, task-success grading, benchmark comparisons, and dashboards
remain intentionally unbuilt. The record contract is in `docs/tech_spec.md`.
