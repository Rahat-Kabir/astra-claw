# Astra-Claw - Technical Specification

## Architecture

### One-shot output ownership (v0.4.6)

`__main__.py` starts the `CliUI` response lifecycle and passes `ui.stream_token`
as `run_conversation(stream_writer=...)`. Plain output streams through the UI;
`finish_assistant_response()` adds its trailing newline without printing the
answer again. Markdown output stays buffered until the final render. This avoids
the default stdout stream printing a first copy outside the UI. Interactive mode
already uses this ownership pattern.

### Bounded tool output (v0.4.5)

`agent/tool_runner.py` calls `agent/tool_output.py::bound_tool_result()` after
every dispatch (including special-case tools), before completion events and
conversation history. Following OpenCode's preview/artifact approach, text is
limited to 2,000 lines or 50 KiB of UTF-8, whichever comes first. Limits apply
to preview text, excluding the JSON envelope and small metadata. Even a single
long line is byte-bounded without splitting a UTF-8 character.

Small JSON results remain unchanged. For `output`, `content`, or `summary`
strings with at most 4 KiB of other metadata, preserve the other fields and save
the complete string as a UTF-8 text artifact. For other shapes, save the entire
pretty-printed JSON document and return its preview, preserving small scalar
exit/status/error fields. Oversized responses include `truncated`, `output_path`,
and `truncation_message`; a tool's own truncation flag never bypasses this cap.
The CLI shows the saved path and shell exit code.

Artifacts live in `get_astraclaw_home()/tool-output/tool_<uuid>.txt`, separate
from workspace edits and the usage ledger. Save errors propagate. On each spill,
remove only matching regular files older than seven days; leave symlinks and
unrelated files alone. No cleanup daemon or new dependency is required. Artifacts
contain full tool text and therefore have the same privacy sensitivity as tool
results; old transcript paths can expire.

`read_file` accepts positive integer `offset` (1-based, default 1) and `limit`
(default/cap 2,000). It streams past preceding lines, reads a page plus one
lookahead line, and returns unchanged page text, `offset`, `lines_read`, and
`next_offset` (null at EOF). Do not prepend line numbers: patch needs original
text. A byte-truncated page can be recovered from its saved artifact; `next_offset`
refers to the original requested page, not just the preview. Very long individual
lines require a shell character slice. Shell output is still captured in memory;
this slice bounds model context, not process memory or disk use.

```text
User Input
    |
__main__.py (parse args, create agent)
    |
cli/repl.py (interactive mode only)
    |
AstraAgent.run_conversation()
    |
System Prompt (prompt_builder.py)
    |
LLM Route Selection + API Call (llm.py + OpenAI SDK)
    |
Tool Calls? -> registry.dispatch() -> Append Results -> Loop back to LLM
    | (no tools)
Final Response
```

## Core Design Decisions

### Request Measurement Contract (v0.4.0)

`usage_ledger.py` writes local evidence to `get_astraclaw_home()/usage/<run_id>.jsonl`.
Each conversation and manual compaction creates a run. Delegates create child runs;
automatic compaction requests remain within their conversation. Background titles
capture the completed conversation as their parent and retain its root ID. The
non-streaming helper also creates a run so direct callers are measured.

The ledger records model calls, not tool results or benchmark correctness:

| Fields | Meaning |
|---|---|
| `schema_version`, `event`, `timestamp` | Version 1; `run_started`, `run_finished`, `request_started`, or `request_finished`; UTC time |
| `run_id`, `root_run_id`, `parent_run_id`, `session_id` | Execution identity and parent linkage; session can be null for one-shot/direct calls |
| `request_id` | Unique ID for one explicit SDK invocation; shared by its start/finish events |
| `operation_id`, `attempt` | Group explicit route fallback or token-parameter compatibility attempts; attempt starts at 1 |
| `provider`, `model`, `purpose` | Requested route and role: conversation, delegate, compaction, title, or direct completion |
| `response_id`, `response_model`, `service_tier`, `finish_reason` | Provider response metadata when available; requested aliases remain separate |
| `status`, `duration_seconds` | Request: completed/failed/interrupted; run additionally supports incomplete/max_turns. Duration uses a monotonic clock |
| `raw_usage` | Provider usage object, retained independently of normalized counts |
| `input_tokens`, `output_tokens`, `total_tokens` | Non-negative integer counts reported by the provider; missing/invalid values are null |
| `cached_input_tokens`, `reasoning_tokens` | Optional provider details; subsets, not extra tokens to add to totals |
| `usage_status` | reported: input and output counts present; partial: only some normalized counts present; missing: no usable counts |
| `error_type`, `http_status` | Error class and HTTP status when available; no exception message |

Streaming calls request `stream_options.include_usage`. Observe usage before
skipping empty-choice chunks. Repeated snapshots replace prior snapshots; they
are not summed. A clean stream end without a finish reason is recorded as
interrupted and makes the run incomplete, while preserving existing return behavior.
An interrupted stream can retain reported usage; execution and usage status are
independent. Detail fields can remain null even when core usage is reported.

Missing data never means zero. Request starts have no usage claim. A start with
no matching finish means unknown outcome/usage after a crash, not success or free
execution. Aggregate finished records once by request ID; include child requests
once by root ID, and report unmatched starts and usage coverage separately. Do
not infer a price or a correctness grade from these records. Total tokens are
not reconstructed from partial counts, and provider totals are not billing receipts.

OpenAI SDK retries are disabled for model clients (`max_retries=0`); Astra's
single-step route fallback and non-streaming token-parameter retry remain and
are recorded separately. Overflow recovery requests get their own operation IDs
within the same run. Credential `/models` probes are outside the model ledger.
Provider-internal retries and charges are not observable here.

No prompts, generated text, tool arguments, credentials, or exception messages
are stored. Ledger writes are serialized within a process; separate runs use
separate files. I/O errors propagate; title generation retains its existing
best-effort behavior. Abrupt termination can leave an unfinished record or line;
no recovery or report reader is included yet. `/usage` remains a context estimate.
Task checkers are described below. Variant comparison and dashboards are deferred.

### Offline Cost Estimates (v0.4.1)

`cost.py::estimate_cost()` enriches each new `request_finished` record. It uses
LiteLLM 1.106.0 only for cost arithmetic; model routing and requests still use
the existing OpenAI SDK. LiteLLM loads lazily with remote price downloads
disabled. Astra reads the package's bundled catalog directly and supplies the
selected rates to `cost_per_token()`; no model or tokenizer call is needed.

| Fields | Meaning |
|---|---|
| `estimated_cost_usd` | Estimated model-token charge, or null; never provider-confirmed billing |
| `cost_status`, `cost_reason` | estimated, or unknown with a machine-readable reason |
| `cost_currency`, `cost_scope` | USD and model_tokens; excludes tool services, cloud compute, taxes, and account discounts |
| `pricing.source`, `pricing.library_version`, `pricing.catalog_sha256` | Bundled LiteLLM source and reproducible catalog identity |
| `pricing.model`, `pricing.entry`, `pricing.effective_rates` | Exact provider-specific model entry and rates used |
| `pricing.service_tier`, `pricing.service_tier_source` | Served tier when reported; otherwise explicitly assumed_default |

Supported scope: completed OpenAI/OpenRouter requests with valid input/output
counts, explicit cache-read counts (unless total input is zero), exact catalog
matches, and flat per-token rates or the verified GPT-5.5 context tiers below.
The served model takes precedence over a
requested alias. There is no fuzzy model lookup or cross-provider price fallback.
Default/standard, priority, and flex tiers require the corresponding rates.
Cache-read tokens are a subset of input; reasoning tokens are a subset of output.
Neither is added again. Missing total_tokens is allowed when input/output are
reported; a conflicting reported total rejects the estimate.

Missing usage, invalid counts, missing cache detail/prices, unknown models,
unsupported providers/tiers, cache writes, reported media-specific token details,
and unverified context-threshold pricing produce unknown cost, not zero. Failed/interrupted
requests retain their token evidence but have unknown full cost. Nonzero price
coverage must not be inferred from zero or null fields. Repeated snapshots are
still priced once per request. No cost aggregates or historical backfill are
included; old ledger rows have no cost fields. Request duration stops before cost
calculation; run duration includes local bookkeeping.

Catalog prices are community maintained and can be stale. Upgrading the pinned
dependency deliberately changes pricing; existing records retain their snapshot.
No live provider bill has been reconciled. New cost fields are additive under
ledger schema version 1; consumers must treat absent fields as unknown.

### GPT-5.5 Context Rates (v0.4.3)

Verified against [OpenAI's GPT-5.5 pricing notes](https://developers.openai.com/api/docs/models/gpt-5.5)
and [API pricing](https://developers.openai.com/api/docs/pricing) on 2026-10-19.
The pinned LiteLLM catalog supplies the rates; these links establish their
meaning, not a runtime dependency on web access.

For `gpt-5.5`, `gpt-5.5-2026-04-23`, and the exact OpenRouter GPT-5.5 entry:

- `prompt_tokens <= 272000` selects short-context rates; `> 272000` selects long-context rates.
- Selection includes cached input and excludes output. The selected rates apply to the whole request, not only tokens above the threshold.
- Standard rates per million tokens: short input/cache/output $5/$0.50/$30; long $10/$1/$45. Cost is `(input - cached) * input_rate + cached * cache_rate + output * output_rate`.
- Service-tier suffixes are applied after the context suffix in the catalog key. Long-context priority prices are absent from the pinned catalog, so those estimates remain unknown. No fallback to short-context or standard prices.
- `pricing.context_threshold_tokens`, `context_band`, `context_basis`, and `rate_keys` identify the selection. Unverified models, thresholds, and tiered schemas remain unknown.

Tests cover below/exactly/above threshold, cache-heavy inputs, served snapshot
IDs, flex/priority gaps, and replay of the prior live pilot's usage. That replay
estimates $0.02141 for three requests. It makes no new model call and does not
reconcile billing. The derivative `cost_replay_v0.4.3.json` retains source hashes;
the historical result and ledger remain unchanged with their original unknown costs.

### Fixed Repair Tasks (v0.4.2, extended v0.4.4)

`scripts/benchmark_port.py` selects one versioned task with `--task`:
`port_validation` (default, ports.py), `slug_normalization` (slug.py), or
`retry_delay` (retry.py). Each task has a prompt, fixture, and independent checker
under `benchmarks/<task>/`. Slug checks cover lowercase ASCII filtering,
separator collapse/trim, Unicode, empty input, generated combinations, and long
text. Retry checks cover the exact schedule, cap, huge attempts, and invalid
types/values. The slug oracle uses a character state machine; the retry oracle
uses an explicit schedule and cap cases. Neither calls the mock repair.
Each invocation
creates a new workspace from the broken fixture and a fresh agent home with a
fixed identity. Memory, skills, titles, compaction, delegation, shell, and fallback
are disabled. Only read_file/write_file/patch on the selected file pass the worker's tool
policy, including attempted calls to tools absent from the advertised schemas.
The normal agent loop is reused; the policy wrapper exists only in that process.

The controller enforces a 90-second worker timeout. With no shell or delegated
workers, killing this worker stops its local task execution. A request already
received by the provider can still incur charges. Default agent limit is six
requests, each with `max_completion_tokens=2048`. This optional model config field
is passed to streaming calls; normal callers that omit it are unchanged.

After the worker exits, a separate `python -I` process runs `check.py` outside the
agent tool workspace with model credentials removed from its environment. It
checks all integers 1..65535, representative out-of-range integers, and invalid
types including booleans. Candidate load/runtime exceptions fail the task;
checker failure, invalid output, or a five-second checker timeout gives an
unknown grade. This is process separation, not an OS sandbox for malicious Python.

`manifest.json` freezes task/version, prompt/fixture/checker/runner/harness hashes,
public config, tool names, Python version, and budgets. No key is saved. Outputs
include execution.json, worker logs, the candidate source, home/usage ledgers, and
result.json. Existing result directories are never reused. Modes mock/mock-noop
exercise the real loop with synthetic model events; live uses the configured
provider/model and requires authorization for paid calls.

`result.json` separates execution status, grade status, and verified_success.
Only a completed execution plus a graded pass is verified success. A timeout
can still have an independently graded output, but is not a verified success.
Usage aggregation deduplicates request identities, exposes unmatched starts and
corrupt/duplicate records, and keeps known token/cost subtotals separate from
complete totals. Missing coverage yields null full totals. Synthetic usage is
labeled and must not be pooled with live measurements. A single live pass is
only a smoke result for this restricted profile, not a general quality claim.

### Session Persistence (JSONL)

- Each session is one `.jsonl` file in `~/.astraclaw/sessions/`
- First line is metadata: `{"type": "meta", "id": "...", "created": "..."}`
- Each later line is a message with an auto-added `ts`
- `ts` is stripped before messages are replayed to the model
- JSONL was chosen over SQLite for zero dependencies and easy inspection
- Manual or automatic compaction archives the old JSONL, then rewrites the session with the compacted transcript and updated compaction metadata
- Session search stays on JSONL for now: `session.py` owns recent-session browsing and two-pass reranked recall so a future SQLite move can swap storage behind the same boundary

### Context Compaction

- `agent/context_compactor.py` estimates request size with a simple char-based heuristic over the system prompt, replay history, pending user input, and tool schemas; `estimate_request_breakdown()` splits that total into system/tools/history for `/usage`
- Compaction keeps the first protected turns and recent tail, then replaces the middle with one synthetic assistant summary message
- Assistant tool-call messages stay attached to their matching tool results so tool history is not split across the compaction boundary
- Repeated compaction folds the earlier synthetic summary into the next summary instead of stacking many summaries
- If the compacted history is not smaller than the original estimate, the rewrite is discarded
- `agent/loop.py` runs preflight compaction before the main model call and retries once on context-overflow errors after forcing compaction
- Summary-generation calls are internal-only and must not stream tokens to the CLI

### Single Source of Truth for Paths

- `constants.py` exposes `get_astraclaw_home()`
- `ASTRACLAW_HOME` can override the default path
- `get_astraclaw_home()` must branch lazily so `ASTRACLAW_HOME` overrides do not evaluate `Path.home()` first
- Other modules should import this helper instead of hardcoding paths

### Tool Registry Pattern

- `tools/registry.py` contains a singleton `ToolRegistry`
- Tools self-register at import time via `registry.register()`
- Each registration now includes:
  - `name`
  - `toolset`
  - `schema`
  - `handler`
  - optional `check_fn`
- `get_definitions(enabled_toolsets=None)` only returns tools that:
  - belong to an enabled toolset, when filtering is requested
  - pass `check_fn()`, when one is provided
- `dispatch()` still executes by tool name and always returns a JSON string

### Toolset Filtering

- Built-in tools are grouped by toolset:
  - `filesystem`: `read_file`, `write_file`, `patch`, `search_files`
  - `terminal`: `shell`
  - `web`: `web_search`, `web_extract`
  - `memory`: `memory`
  - `skills`: `skills`
- `agent/loop.py` reads optional `tools.enabled_toolsets` from config and passes that filter into the registry
- If no toolset filter is configured, all registered and available tools are exposed

### Availability Checks

- A tool may provide a `check_fn` to determine whether it should be exposed to the model
- If `check_fn()` returns `False`, the tool schema is omitted
- If `check_fn()` raises an exception, the tool is skipped rather than crashing schema generation
- This is intended for future tools that depend on API keys, installed binaries, or external services

### Search Tool

- Two modes:
  - `target="content"` uses grep/findstr-like search
  - `target="files"` uses find/dir-like filename search
- Cross-platform behavior is selected from the current OS
- Results are capped at 50 lines/files

### Web Tools

- `astra_claw/tools/web_tools.py` provides Tavily-backed `web_search` and `web_extract`
- Both tools are synchronous and return JSON strings through the normal registry path
- `check_fn` hides both schemas unless `TAVILY_API_KEY` is set
- `web_search` returns compact metadata only: `title`, `url`, `description`, `position`
- `web_extract` accepts up to 5 URLs, validates `http/https`, supports `format` (`markdown` or `text`) and `extract_depth` (`basic` or `advanced`)
- Extracted content is capped at 8000 chars per URL and marks `truncated: true` when clipped

### Session Search Tool

- `astra_claw/tools/session_search_tool.py` is a thin wrapper over `session.py`
- Two modes:
  - empty query -> recent sessions (`list_recent_sessions`)
  - non-empty query -> cross-session search (`search_sessions`)
- Search is JSONL-native and two-pass:
  - pass 1 reads only session meta/title + recency to build a shortlist
  - pass 2 loads only shortlisted transcripts and reranks with message content
- Scoring uses fixed heuristics:
  - exact phrase in title: `+100`
  - exact phrase in body: `+40`
  - per-term in title: `+20`
  - per-term in user/assistant: `+10`
  - per-term in tool output: `+3`
  - recency bonus: `max(0, 14 - days_old)`
- Results are grouped by session, not by message, and include `session_id`, `title`, `created`, `message_count`, `score`, `preview`, and up to 3 snippets
- Current session is excluded by threading `current_session_id` through `run_conversation(...)->execute_tool_calls(...)`
- `role_filter` is optional and limits search to `user`, `assistant`, and/or `tool`

### Shell Tool Safety

- Regex patterns detect dangerous commands such as recursive delete, `mkfs`, `dd`, SQL `DROP`, and `curl|sh`
- `classify_command_risk()` combines those destructive checks with command-boundary-anchored package mutation checks for Python (`pip install`, `python -m pip install`, `uv pip install`, `uv run --with`, `uv tool install`, `uvx`), JavaScript (`npm`/`pnpm`/`yarn`/`bun` installs plus `npx`/`bunx`/`pnpm dlx`), and Windows system installers (`winget`, `choco`, `scoop`)
- `set_approval_callback()` lets `__main__.py` inject an interactive approval prompt
- Without a callback, dangerous commands are blocked
- Rejected package mutations never reach `subprocess.run`; ordinary commands such as `uv run pytest` and `npm test` remain ungated
- The Windows shell hint now reflects `subprocess.run(..., shell=True)` behavior more precisely: Windows commands should remain `cmd`-compatible

### Native Image Attachments

- Core contract change: a user message may now hold either a text string or an OpenAI-compatible content-block list (`text` plus one or more `image_url` data URLs). Text-only turns keep the original string shape.
- `cli/image_attachments.py` discovers only real paths present in the user's prompt. Direct images attach immediately; a folder with one supported image auto-selects it; a folder with several uses the existing CLI clarify callback to ask which one. One-shot mode cannot ask, so it warns and attaches none.
- Image type is detected from file signatures rather than extensions. Supported inputs are PNG, JPEG, GIF, and WebP, capped at 10 MB each and 4 images per prompt. Sensitive paths reuse `tools/path_safety.py` blocking.
- Selected image bytes are base64-encoded into `data:<mime>;base64,...` URLs. The text block includes the resolved image paths so the model can associate content with filenames.
- Multimodal user messages are written directly into the session JSONL. Resume and `/retry` therefore replay the original bytes even if the source file moves. Session preview/search extracts only text blocks and an image marker.
- Compaction estimates each image as a fixed 1200 tokens instead of counting base64 characters. Compaction summaries replace image payloads with `[image attachment]`, preventing large encoded data from entering the summarization prompt.
- Astra-Claw does not maintain a model-capability catalog in v1. The configured provider/model must accept image input; provider errors remain visible rather than silently falling back to OCR.

### CLI/TUI Layer

- Interactive mode uses `prompt_toolkit` for input history, slash command completion, and prompt handling
- Rich is used for light output: startup banner (session id, primary `provider:model` route, optional title/workspace/resume stats), help, session table, warnings, errors, and the live feedback spinner
- Slash commands (`/help`, `/sessions`, `/new`, `/compact`, `/usage`, `/model`, `/retry`, `/skills`, `/skill`, `/exit`, `/quit`) are handled locally; skill aliases (`/<skill-name>`) and `/skill` rewrite the prompt before the LLM call, and the others are not sent to the LLM
- `agent/loop.py` exposes an optional `stream_writer(token)` callback so the CLI owns token rendering
- When no callback is provided, the agent keeps the old stdout streaming behavior
- `/compact` runs manual compaction, archives the current session, rewrites the transcript, and replaces the REPL's active replay history
- `/usage` builds a local context panel from the current replay history: estimated next-request tokens (system + tool schemas + history), compaction threshold/headroom, session compaction count, memory char limits, and last-turn heartbeat stats. Estimates reuse the compactor's char/4 heuristic; no provider billing data and no LLM call
- `/retry` uses `cli/history_edit.py` to find the last user message, drop that turn from `active_history`, archive + rewrite the session JSONL, then fall through to a normal agent turn with the same user text (including any tool messages from that turn)
- `/model` switches the active model without a restart: `cli/commands.py::parse_model_arg` parses `provider:model` or a bare `model` (keeping the current provider), the REPL validates the resolved key via `llm.validate_credentials` (fail fast), then `agent.set_primary_route()` updates `primary_route` + in-memory model config and warms the per-provider client, and `save_user_config` persists `model.provider`/`model.default`. Bare `/model` prints the current route via `ui.print_model_info`
- Preview-and-approve edits: `write_file`/`patch` compute a unified diff (shared `path_safety.unified_diff`) and call `path_safety.request_write_approval(path, diff, action)` before `atomic_write_text`. The approval callback is a module-level hook (`set_write_approval_callback`), the same shape as `shell_tool`'s dangerous-command approval; when unset, writes proceed (so non-interactive callers don't hang). A reject returns `{"status": "rejected_by_user"}`. The REPL builds `_build_write_approval_callback` — stops the spinner, renders the diff via `ui.print_diff` (green/red, line-capped), reads `y`/`n`/`a`; `a` latches a session-wide "always" flag inside the closure so the tool side stays a plain bool. Gated by `cli.confirm_edits` (default True) and cleared on REPL exit. `unified_diff` normalizes both sides to end with `\n` before diffing, so a file whose final line lacks a trailing newline can't collapse a `-`/`+` pair onto one physical (and thus mis-colored) line; this affects only the displayed diff, never the written bytes

### Usage Panel

- `cli/usage.py` owns the pure snapshot builder: `build_usage_snapshot(...)` returns a frozen `UsageSnapshot` dataclass from the live agent, active history, session meta, and heartbeat counters
- `agent/context_compactor.py` exposes `estimate_request_breakdown()` and `compaction_threshold_budget()` so `/usage` and compaction share one threshold formula
- `agent/loop.py` exposes `get_system_prompt_text()` so the CLI can estimate system-prompt size without reaching into private helpers
- `cli/ui.py` renders the Rich panel via `print_usage_panel(snapshot)` and exposes read-only heartbeat state through `get_heartbeat_snapshot()`
- Last-turn streamed tokens come from the same heartbeat counters used during agent turns (`len(token) // 4`); they reset when the turn ends

### Markdown Rendering

- `cli.render_markdown` in `config.yaml` toggles formatted assistant output (default `false`)
- When off, `cli/ui.py` streams tokens live via `stream_token()` with `markup=False` (raw text, including `**`)
- When on, the REPL buffers streamed tokens during the turn (spinner only), then `finish_assistant_response(full_text)` prints the full reply once through Rich `Markdown`
- `begin_assistant_response()` resets per-turn stream state; plain mode adds a trailing newline after the streamed block
- Interactive mode reads the flag from `agent.config` each turn via `set_render_markdown()`; one-shot mode in `__main__.py` uses the same `CliUI.finish_assistant_response()` path
- Session JSONL and compaction replay keep the raw assistant string; rendering is display-only

### Lightweight Skills

- Skills are user-owned markdown files at `~/.astraclaw/skills/**/SKILL.md`
- `cli/skills.py` scans recursively, skips noisy dependency/cache folders, caps each skill file at 64 KB, parses simple optional frontmatter keys (`name`, `description`), and normalizes CRLF line endings before frontmatter parsing
- `list_skills()` returns unique slugified skill metadata; `build_skills_index()` renders a compact `<available_skills>` prompt block
- `prompt_builder.py` appends only the compact skill index to the system prompt, keeping full skill bodies out of the prompt unless invoked
- `/skills` lists installed skills in the CLI; `/<skill-name> [request]` and `/skill <name> <request>` wrap the full `SKILL.md` body (plus optional user request) into one turn, then still pass through context-reference expansion
- `get_skill_commands()` and `resolve_skill_command()` register one slash alias per installed skill; built-in slash commands win on name collisions; underscore/hyphen aliases are interchangeable
- Slash-command tab completion merges static commands with installed skill aliases
- `tools/skills_tool.py` exposes agent-driven progressive disclosure: `skills(action="list")` returns metadata only; `skills(action="view", name=...)` returns raw `SKILL.md` content as JSON
- The `skills` tool is hidden unless at least one skill is installed (`check_fn` over `list_skills()`); no special-casing in `tool_runner.py`
- v0.2.x is explicit load-on-demand only: no skill install/update hub and no persistent active-skill session state

### Context References

- `astra_claw/cli/context_refs.py` expands inline refs before user text reaches `AstraAgent.run_conversation()`
- Supported refs: `@file:path`, `@file:path:10-25`, `@folder:path`, `@diff`, and `@session:<id>`
- Interactive mode expands refs in `cli/repl.py`; one-shot mode expands refs in `__main__.py`
- Expanded content is appended under `--- Attached Context ---` so the original prompt remains visible
- File and folder refs resolve inside `get_workspace_fence()`, reject sensitive paths via `tools/path_safety.py`, reject binary/non-UTF-8 file content, and cap output sizes
- `@folder:` emits a bounded tree listing only; it does not read every file in the folder
- `@diff` runs `git diff --no-ext-diff -- .` from the workspace fence and attaches the unstaged diff
- `@session:` loads a past JSONL transcript via `session.load_session()` and rejects attaching the current session to itself
- `cli/context_completion.py` powers REPL tab completion for context refs: `@` suggests ref types; `@file:` / `@folder:` use directory listing when browsing (`path/` or empty partial) and fuzzy workspace search when a name fragment is typed (substring + token match, ranked, capped at 25); `@session:` matches session id or title; completion rows include lightweight file-size / folder-count meta

### Live Feedback Surface

- `agent/events.py` defines `AgentEvents` (frozen dataclass) with three optional hooks: `on_thinking(active)`, `on_tool_start(call_id, name, args)`, `on_tool_complete(call_id, name, args, result)`
- `run_conversation(..., events=None)` keeps the surface opt-in; any missing hook is a no-op and the agent behaves identically when called without events
- `agent/streaming.py` fires `on_thinking(True)` before each streamed LLM call and `on_thinking(False)` on the first content or tool-call delta; compaction summary streams are called with `on_thinking=None` so the user's spinner only tracks user-facing turns
- `agent/tool_runner.py` brackets every dispatch with `on_tool_start` / `on_tool_complete` and preserves the `memory` tool special-case that injects the agent's `MemoryStore`
- `cli/tool_display.py` holds pure preview + summary helpers (no Rich deps): `build_tool_preview` picks the primary arg per tool (path, pattern, command, action+target) and `summarize_tool_result` parses the JSON result into a short human label (line counts, `+N -M` for patch, exit codes for shell, session counts for `session_search`, etc.)
- `cli/ui.py` owns heartbeat state independently from its renderer: `start_thinking(label)` starts or resumes preserving counters, `pause_thinking()` hides it without resetting state so streamed tokens print cleanly, and `stop_thinking()` fully resets at turn end. At the idle prompt Rich renders `<label> · <N> tools · <elapsed> · ~<tokens> tok` with a 0.5s daemon-thread tick. During async follow-up input, `set_prompt_owned_live_rendering(True)` suppresses Rich `Status` and `heartbeat_text()` supplies the same state to prompt_toolkit's bottom toolbar. `bump_tool()`, `bump_tokens(n)`, and `set_heartbeat_label(label)` mutate counters between events. `print_tool_line(name, preview, summary)` renders one compact dim line per completed tool; errors show in red, no emoji. Assistant replies finish through `begin_assistant_response()` / `stream_token()` / `finish_assistant_response()` (plain stream or Rich Markdown when `cli.render_markdown` is enabled)
- `cli/repl.py` builds an `AgentEvents` per turn: `on_thinking(True)` starts the heartbeat, `on_thinking(False)` pauses it during streaming, `on_tool_start` resumes with `running <tool> <preview>`, `on_tool_complete` pauses, bumps the tool counter, and prints the tool line. The `stream_writer` is wrapped to call `bump_tokens(len(token) // 4)` for a rough live token estimate. `run_conversation` is wrapped in `try/finally` so `stop_thinking()` always runs at turn end, then `finish_assistant_response(response)` renders the assistant block

### Queued Follow-up Messages

- Interactive turns run through `asyncio.to_thread(_execute_agent_turn, ...)`, leaving the main prompt_toolkit event loop free to await `PromptSession.prompt_async()` at `follow-up>`.
- The async runner enters `patch_stdout(raw=True)` after the event loop starts. Raw mode preserves Rich ANSI sequences instead of sanitizing the escape byte into visible `?`; prompt_toolkit is the sole live renderer and refreshes its heartbeat toolbar every 0.5 seconds, avoiding cursor collisions with Rich `Status`.
- `cli/followup.py::FollowUpQueue` stores submitted text in thread-safe FIFO order. After the current turn is rendered and persisted, the REPL pops one message, passes the completed history into the next `run_conversation()` call, and continues collecting more follow-ups.
- `PromptBroker` bridges synchronous worker callbacks back to the main input loop. A write approval or `clarify` question cancels the active follow-up prompt, receives exclusive terminal input, resolves the worker's `Future`, and then restores any partially typed follow-up draft.
- Slash commands other than `/steer` are rejected while a turn is running; they remain local idle-REPL operations. Ordinary follow-ups never alter the active turn.

### Safe Mid-run Steering

- `cli/followup.py::SteeringQueue` is a thread-safe FIFO separate from `FollowUpQueue`. At the busy `follow-up>` prompt, only explicit `/steer <message>` (or `/steering <message>`) enters it; ordinary text retains next-turn semantics and other slash commands remain rejected. The canonical command and alias live in `cli/commands.py`, so completion and `/help` expose them; idle use prints a busy-only warning instead of reaching the model.
- `_execute_agent_turn()` passes `steering.pop` into `AstraAgent.run_conversation()` as the optional `steering_reader` callback. `agent/loop.py` polls once after a whole tool-call batch completes, appends `{"role": "user", "content": "[steering]\\n..."}` to both replay history and `new_messages`, then the next model request sees the redirected instruction.
- Steering is cooperative, not forceful cancellation: an active model stream, shell command, write, or multi-tool batch is never killed halfway through. One message is consumed per safe boundary. If the agent finishes naturally before polling, the REPL pops the undelivered steering message before ordinary follow-ups and runs it as the next user turn, so timing races do not lose input.
- The prompt_toolkit bottom toolbar is the steering acknowledgement channel: enqueue sets `steering queued (N)`, the worker-side reader sets `steering applied` when the agent loop consumes a message, and late fallback shows `steering running as next turn`. `CliUI.heartbeat_text()` keeps this state visible even when streamed assistant output pauses the normal heartbeat.

### Memory System

- Storage: `~/.astraclaw/memory/MEMORY.md` (agent notes) and `USER.md` (user profile)
- Entries are joined by the `§` section delimiter and stored as plain text
- `MemoryStore` (in `astra_claw/memory.py`) owns persistence, char limits, and content scanning
- `tools/memory_tool.py` is a thin wrapper: schema + JSON dispatch over `MemoryStore`
- Single `memory` tool with actions `add` / `replace` / `remove` and targets `memory` / `user`
- Char limits (not token limits) keep budgets model-independent
- Frozen snapshot: `load_from_disk()` runs once at agent init; the system prompt never changes mid-session, keeping the prefix cache stable. The snapshot refreshes on the next session start.
- Content scanning rejects prompt-injection, exfiltration, and invisible-unicode payloads before persistence because entries are injected into the system prompt
- Atomic writes via temp-file + `os.replace`; no file locking (single-user CLI)
- The agent loop special-cases the `memory` tool so the handler receives the agent's `MemoryStore` instance. Standalone `registry.dispatch("memory", ...)` returns an unavailable-error JSON, keeping the registry contract uniform.
- `build_system_prompt(memory_store, include_memory_hint=None)` layers: SOUL/identity -> `TOOL_POLICY` -> env + shell hint -> optional workspace-fence line (only when `--workspace` is explicitly set) -> memory hint (auto-on when `memory_store` is passed) -> user + memory blocks. `TOOL_POLICY` is a separate layer so SOUL.md cannot drop tool rules.

### Todo / Planning Tool

- Session-scoped `TodoStore` owned by the agent (one per session, not persisted to disk)
- Single `todo` tool: pass `todos` to write, omit to read; every call returns the full list plus `{total, pending, in_progress, completed, cancelled}` summary counts
- `merge=false` (default) replaces the whole list; `merge=true` updates items by id and appends new ones
- Valid statuses: `pending` / `in_progress` / `completed` / `cancelled`; invalid values normalize to `pending`
- Toolset: `planning`, so it can be disabled via `tools.enabled_toolsets` config
- Same special-case pattern as `memory`: `agent/tool_runner.py` routes `fn_name == "todo"` to a handler with the store injected; standalone `registry.dispatch("todo", ...)` returns an unavailable-error JSON
- `TodoStore.format_for_injection()` renders active (pending / in_progress) items; `_maybe_compact_history` in `agent/loop.py` appends that rendering as a synthetic user message after compaction so the plan survives context trimming

### Clarify Tool

- Thin shell: `astra_claw/tools/clarify_tool.py` validates the question + choices (max 4, blanks filtered) and delegates to a platform-provided `callback(question, choices) -> str`. The tool itself never touches UI code.
- Same special-case pattern as `memory` / `todo`: `agent/tool_runner.py` routes `fn_name == "clarify"` and injects `clarify_callback` from `run_conversation`. Standalone `registry.dispatch("clarify", ...)` returns an "unavailable" error JSON so non-interactive callers get a clean failure instead of hanging.
- CLI callback lives in `cli/repl.py::_build_clarify_callback`: stops the thinking spinner, renders the question via `cli_ui.print_clarify_question`, and reads one line from the existing `PromptSession`. During a background turn, `PromptBroker` gives the question exclusive access to that prompt. Numeric input in range resolves to the matching choice text; anything else (including the implicit "Other" option) is returned verbatim. `KeyboardInterrupt` / `EOFError` return an empty string so the agent can continue.
- Toolset `clarify` (can be disabled via `tools.enabled_toolsets`).
- Out of scope for v1: arrow-key navigation, timeout / auto-proceed, and non-CLI gateway wiring.

### Delegation / Sub-agents

- `astra_claw/tools/delegate_tool.py` exposes the `delegate` tool (toolset `delegation`). It spawns one fresh `AstraAgent` per call, runs it to completion **synchronously**, and returns its final message as a JSON summary. v1 is single-child and blocking — no threading, no parallel/batch mode (threading is unsafe against JSONL writes and the Rich UI).
- **Isolation is the whole point.** The child runs in a brand-new context with no parent history. Its system prompt is a focused briefing built from `goal` + `context` only — the parent must pass every needed fact (file paths, error messages, constraints) explicitly. The child's intermediate tool calls and reasoning never enter the parent's context window; only the summary does.
- **Child construction.** `_build_child_config()` deep-copies the parent config, disables memory (`enabled` / `user_profile_enabled` = False), caps turns (`delegation.max_turns`, default 15, hard cap 30), and sets the child's `enabled_toolsets` to the parent's set (or all registered toolsets when the parent enables "all") **minus** the blocked set `{delegation, clarify, memory, planning, session_search}`. The child is built via `AstraAgent(config=..., system_prompt_override=briefing)`, where `system_prompt_override` short-circuits `_build_system_prompt_text()` so SOUL.md + memory are skipped.
- **Recursion is impossible by construction.** Because `delegation` is a blocked toolset, the child's tool schemas never include `delegate` — it cannot see, let alone call, the delegation tool. No depth counter is needed (contrast hermes-agent, which uses a `MAX_DEPTH` counter to allow grandchildren).
- **Exit handling.** Natural finish (assistant reply, no tool calls) → `exit_reason: "completed"`. Hitting the turn cap returns the loop's sentinel text, which `_detect_exit()` discards in favor of the child's last substantive assistant message → `exit_reason: "max_turns"` with the partial findings preserved. An exception returns `{"status": "error", ...}` so the parent can re-plan.
- **Child session persistence.** Each child run is saved as its own JSONL session via `create_session()` + `rewrite_session()` with `parent_id` in the meta line and a `[delegate] <goal>` title — a debugging aid. This is the one place an exception is swallowed (logged warning): a session-save failure must not discard an otherwise-successful delegation result.
- **The briefing prompt matters more than the orchestration.** The child briefing must include the imperative "actually call the tool, don't describe" — without it, weaker models (observed on gpt-4o-mini) hallucinate tool use and report fabricated results. This was caught only by the real-model smoke (`scripts/smoke_delegate.py`), not by the mocked unit tests, and is now guarded by a regression assertion.

### Special-Case Tool Injection

- `memory`: injects the agent `MemoryStore`
- `todo`: injects the per-session `TodoStore`
- `clarify`: injects the CLI callback
- `session_search`: injects `current_session_id` so the active session never appears in recall results
- `delegate`: injects `parent_config` (for child construction), `parent_session_id` (for the child's `parent_id` link), and `events` (forwarded to the child with `on_thinking` stripped, so the parent spinner only tracks user-facing turns)

### Session Title Auto-generation

- `astra_claw/agent/title_generator.py` generates a 3-5 word title from the first **substantive** user/assistant exchange using a cheap, non-streaming LLM call (`llm.complete_once`)
- Greeting-only openers (`hey`, `hello`, `thanks`, short small talk) are skipped via `is_low_signal_user_message()`; titling can land on a later turn until a real topic appears
- Runs on a **daemon thread** after each eligible user-facing turn while the session is still untitled, so it never blocks the reply
- Silent-fail by design: any exception (bad request, 401, timeout) returns `None` and the session simply stays untitled
- Title resolves a model via: `compression.summary_model` -> `model.fallback_model` -> `model.default`; same provider as the primary route
- Output cleanup: strips matching quotes, strips a leading `Title:` prefix, strips trailing `.!?,;:`, truncates to 80 chars with `...`
- Storage: `title` + `titled_at` are written into the session's meta (line 1 of the JSONL) via `rewrite_session(..., meta_updates=...)`. One full-file atomic rewrite per session, once.
- `session.get_session_title()` short-circuits so an already-titled session is never re-titled automatically (user-set titles are also preserved)
- `cli/repl.py` tracks every spawned title thread in a `pending_title_threads` list and joins them with a 5s per-thread timeout on exit (inside a `try/finally` around the input loop) so daemon threads don't die with the process mid-API-call. The spinner shows `Saving session titles` during the join.
- `llm.complete_once()` tries `max_completion_tokens` first (required by gpt-5.x and reasoning models) and falls back to legacy `max_tokens` on an `unsupported_parameter` error, so the helper is model-agnostic
- Config: `session.auto_title: True` default; set to `False` to disable the feature entirely

### SOUL.md Identity Layer

- Storage: `~/.astraclaw/SOUL.md`
- `astra_claw/soul.py` owns starter-file seeding, loading, scanning, and truncation
- `ensure_astraclaw_home()` seeds a default `SOUL.md` on first run if the user does not already have one
- `load_soul_md()` returns `None` when the file is missing, empty, unreadable, or unusable; prompt assembly then falls back to `DEFAULT_IDENTITY`
- Valid `SOUL.md` content becomes slot #1 of the system prompt, ahead of memory and environment hints
- Content is security-scanned for prompt-injection / invisible-unicode payloads and truncated with a head/tail marker if oversized

### File Tools Safety

- `write_file` and `patch` share path safety helpers for workspace fence checks, protected paths, and atomic text writes
- `patch` performs exact text replacement on existing files, requires a unique match unless `replace_all=true`, and returns a unified diff
- File-writing tools block writes to sensitive paths such as `.env`, `.git`, `.ssh`, and credential-like filenames
- Blocked patterns are checked against the resolved path parts
- Context references reuse the sensitive-path blocklist for read attachments, while `read_file` itself remains an unfenced tool
- Workspace fence runs **before** the blocklist: when `--workspace <path>` is passed, writing tools reject any resolved path that does not sit under `get_workspace_fence()`. Fence is unset by default and falls back to cwd, so existing behavior is preserved when the flag is absent.
- Fence scope is intentionally narrow: only writing tools are jailed. `read_file` stays unfenced (reads are non-destructive) and `shell` is unfenced (chdir inheritance already scopes normal commands; fully jailing shell args is out of scope because of Windows quoting + pipes + redirects). The dangerous-command approval callback remains the defense for destructive shell usage.

### Config: Defaults + User Overrides

- `DEFAULT_CONFIG` lives in `config.py`
- User overrides are loaded from `~/.astraclaw/config.yaml`
- Nested dictionaries are deep-merged
- Optional `tools.enabled_toolsets` can limit which tool families are exposed to the model
- `memory.enabled`, `memory.user_profile_enabled`, `memory.memory_char_limit`, `memory.user_char_limit` control the memory system; the agent creates a `MemoryStore` if either `enabled` flag is true
- `model.fallback_provider` and `model.fallback_model` configure the one-step provider fallback route
- `model.context_window` and the `compression.*` keys configure compaction thresholds and protected history windows
- `SOUL.md` does not currently have config knobs; it is a first-run home-level file rather than a config-driven feature

### LLM Integration

- Uses the `openai` Python SDK with `stream=True`
- Tokens stream through an optional caller-provided callback, with stdout fallback
- Tool calls are accumulated silently, then dispatched after the streamed response finishes
- OpenAI and OpenRouter are both treated as OpenAI-compatible providers
- `astra_claw/llm.py` centralizes provider base URLs, API key lookup, route resolution, and transient-error classification
- The agent tries the primary provider/model first, then retries once on the configured fallback provider/model when the primary fails before meaningful streamed output
- Fallback only applies to transient/runtime failures such as timeouts, connection errors, 429s, and 5xx responses. Auth and malformed-request failures do not fail over.

## File Dependency Chain

```text
constants.py       (no deps)
config.py          (imports constants, soul)
llm.py             (imports OpenAI SDK + usage_ledger)
usage_ledger.py    (imports constants + cost)
cost.py            (lazy LiteLLM cost utilities + bundled catalog)
session.py         (imports constants)
memory.py          (imports constants)
soul.py            (imports constants)
tools/registry.py  (no deps)
tools/*.py         (import registry; memory_tool also imports memory; todo_tool/session_search_tool are thin wrappers)
tools/web_tools.py (imports registry only + stdlib HTTP helpers)
agent/events.py    (no deps)
agent/streaming.py (no agent-local deps; iterates SDK stream + on_thinking)
agent/tool_runner.py (imports memory, tools.memory_tool, tools.todo_tool, tools.session_search_tool, tools.registry, events)
agent/title_generator.py (imports llm, session)
agent/loop.py      (imports config, llm, memory, prompt_builder, registry, events, streaming, tool_runner)
cli/context_refs.py (imports constants, session, tools.path_safety)
cli/skills.py       (imports constants; no Rich or prompt_toolkit)
cli/tool_display.py (pure helpers; no Rich or prompt_toolkit)
cli/usage.py       (pure helpers; no Rich or prompt_toolkit)
cli/*.py           (imports constants, session, Rich, prompt_toolkit, agent.events, cli.context_refs, cli.skills, cli.tool_display, cli.usage)
__main__.py        (imports loop + cli + session)
```

## Tech Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Language | Python 3.11+ | Best LLM SDK support |
| LLM SDK | `openai` | Works with OpenAI + OpenRouter through one client |
| Config | PyYAML | Simple and human-readable |
| CLI input | `prompt_toolkit` | History, completion, and better prompt behavior |
| CLI output | Rich | Lightweight panels/tables/colors |
| Tool calling | OpenAI function calling format | Standard schema format |
| Sessions | JSONL files | Zero deps and easy debugging |
| User data | `~/.astraclaw/` | Kept outside the repo |

## Supported Providers

| Provider | Base URL | Env Var |
|----------|----------|---------|
| OpenAI | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| OpenRouter | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` |

### Setup Wizard

- `cli/setup.py` runs an interactive three-step wizard (provider, API key, default model)
- Curated provider list is hardcoded: OpenAI and OpenRouter only; each provider has a small curated model list plus a `Custom model name` escape hatch
- API key is validated by `llm.validate_credentials()` which pings `/models` with a 5-second timeout before saving; bad keys never reach disk
- Output is persisted via `config.save_user_config()` which atomically merges the wizard's partial config into `~/.astraclaw/config.yaml` (only the keys the user changed; defaults stay implicit so future default updates still propagate)
- Section flags (`astraclaw setup model | key | provider`) re-run a single step against the existing file; provider switches invalidate the stored API key for the previous provider
- All prompts are dependency-injected (`input_fn`, `choice_fn`, `validate_fn`) so the wizard is unit-testable without real stdin or network calls

### First-Run Guard

- `__main__.py` calls `_has_usable_credentials()` before entering chat mode and offers to launch the setup wizard when no key is reachable
- The guard runs only in chat mode (with or without `--session`); one-shot mode and `--sessions` skip it
- A non-interactive stdin (no TTY) prints a one-line "configure manually" message and exits non-zero instead of hanging on `input()`
- Credential resolution: `llm.resolve_api_key(provider, model_config)` prefers `model.api_key` from yaml, then falls back to the provider's environment variable

## Testing Strategy

- `tests/test_features.py` covers core regressions for constants, config, registry behavior, and prompt assembly
- `tests/test_session.py` covers JSONL session persistence, recent-session listing, and JSONL session-search ranking/exclusion behavior
- `tests/test_memory.py` covers `MemoryStore` add/replace/remove, char limits, threat scanning, and frozen-snapshot stability
- `tests/test_soul.py` covers first-run seeding, no-overwrite behavior, loading, fallback, threat blocking, and truncation
- `tests/test_workspace.py` covers the `--workspace` flag and the write fence (inside-ok, relative escape blocked, absolute escape blocked, no-fence fallback, flag parsing, bad path exit)
- `tests/tools/test_patch_tool.py` covers exact replacement, deletion, no-match, multi-match, `replace_all`, protected paths, workspace escapes, and schema registration
- `tests/agent/test_loop.py` also covers primary success, transient fallback success, and no-fallback cases for bad requests
- `tests/agent/test_context_compactor.py` covers token estimation, protected windows, summary reuse, and no-benefit compaction rejection
- `tests/cli/` covers slash commands, completion, skill discovery/invocation, REPL routing, `/usage` snapshot tests, Markdown rendering tests, context-reference expansion, session switching, and stream callback use
- `tests/tools/` contains module-level tests for file tools, shell execution, search behavior, session-search behavior, and the memory tool wrapper
- `tests/tools/test_web_tools.py` covers Tavily schema gating, normalization, truncation, and validation errors
- `tests/agent/` contains mocked loop tests for streaming and tool-call orchestration without live API calls
- `tests/agent/test_events.py` covers `AgentEvents` wiring: thinking toggles, tool start/complete ordering, `events=None` back-compat, and compaction silence
- `tests/cli/test_tool_display.py` covers preview + summary helpers for all 7 tools plus error paths
- `tests/agent/test_title_generator.py` covers title cleanup (quotes, prefix, truncation), silent-fail on exception, skip when already titled, greeting/small-talk skip, later substantive turn titling, daemon-thread wiring
- `tests/cli/test_setup.py` covers the full wizard, section flags, key validation, keep-existing-key, custom-model path, and provider-change key invalidation
- `tests/test_config.py` covers `save_user_config()` partial overrides, merge-into-existing, and `load_user_config()` empty-file behavior
- `tests/test_llm.py` covers `resolve_api_key()` precedence, `create_client()` explicit-key passthrough, and `validate_credentials()` success / unauthorized / timeout / empty-key paths
- The full suite is run with `python -m pytest tests -v`
- Focused commands and suite layout live in `docs/testing.md`

## /undo (v0.3.3)

- The undo stack lives in `tools/path_safety.py` beside the write-approval gate it complements: an in-memory LIFO list capped at 25 entries, cleared by the REPL at startup (session-scoped; one-shot mode, delegate children, and tests accumulate harmlessly).
- Each successful `write_file`/`patch` banks `(resolved_path, old_content, existed, sha256(new_content))` AFTER the write returns - a failed write leaves no entry, so `/undo` can never revert a transition that never happened. Resolving the path at capture time prevents a later cwd change from redirecting undo to a same-named file.
- `undo_last_write()` peeks the newest entry and rechecks the workspace fence/protected-path rules before touching disk. It also refuses on any post-write divergence: content-hash mismatch (`refused_modified`) or existing file deleted (`refused_missing`). Refusals keep their entry; restore failures (`error`) also keep it; only success pops. A created file that is already gone resolves as `already_gone` (that IS the undone state).
- Chained writes to one file verify cleanly because each entry's `written_hash` equals the previous entry's post-write content.
- `/undo` is a local REPL command (no LLM call, no tool schema): the model is told about successful undos through a synthetic `[undo]` user message appended to history + JSONL, because a stale full-file rewrite would otherwise silently re-apply the undone write. `/retry` skips these internal notes when locating the last real user prompt. Refusals inject nothing - no divergence means nothing to correct.
- Deliberately skipped from Hermes-style checkpointing: shadow git store, retention GC, whole-tree restore, undo-of-undo. The approval gate guarantees a human approved each write moments earlier; a bounded RAM stack covers that risk window.
- `write_file` fail-fast change (v0.3.3): an existing file that cannot be read returns an error instead of being treated as empty - the old behavior lied in the approval diff and would have let undo "restore" non-empty files as empty.

## Delegate child-session demotion (v0.3.4)

- Delegate runs persist as their own JSONL sessions with `parent_id` in meta (v0.3.0). Left alone, `session_search` ranked those child transcripts like real conversations, so the agent could "recall" its own intermediate tool noise as if it were past work.
- Fix is in `session.py`, not the tool: `_demote_children()` is a stable two-bucket reorder (real sessions first, children appended last) applied to the `search_sessions` candidate shortlist, the recent-session fallback list, and the final score-sorted results; `list_recent_sessions` puts children in a second bucket that only fills leftover result slots. Children therefore still surface when nothing else matches - recall stays complete, it just prefers real conversations.
- Results carry `is_child` so the model can weigh them; `include_children=True` (parameter on both functions and the `session_search` schema) disables demotion entirely. The human-facing `/sessions` listing is intentionally unchanged.
