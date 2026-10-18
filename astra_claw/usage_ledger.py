"""Append-only model request evidence. No prompts, responses, or credentials.

Run IDs describe execution, not task correctness. Missing usage is never zero.
Context variables link synchronous delegate runs without changing tool schemas.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
import json
from pathlib import Path
from threading import Lock
from time import perf_counter
from types import SimpleNamespace
from uuid import uuid4

from .constants import get_astraclaw_home
from .cost import estimate_cost


_write_lock = Lock()
_current_run = ContextVar("usage_run", default=None)


def _now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class UsageRun:
    run_id: str
    root_run_id: str
    parent_run_id: str | None
    session_id: str | None
    purpose: str
    path: Path
    status: str = "completed"


def _append(run, event, **fields):
    record = {
        "schema_version": 1,
        "event": event,
        "timestamp": _now(),
        "run_id": run.run_id,
        "root_run_id": run.root_run_id,
        "parent_run_id": run.parent_run_id,
        "session_id": run.session_id,
        **fields,
    }
    line = json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
    # Each run has its own file; the lock also serializes same-process writers.
    # I/O failures propagate: silently losing evidence would invalidate accounting.
    with _write_lock:
        run.path.parent.mkdir(parents=True, exist_ok=True)
        with run.path.open("a", encoding="utf-8") as stream:
            stream.write(line)


@contextmanager
def run_scope(purpose, session_id=None):
    parent = _current_run.get()
    run_id = uuid4().hex
    run = UsageRun(
        run_id=run_id,
        root_run_id=parent.root_run_id if parent else run_id,
        parent_run_id=parent.run_id if parent else None,
        session_id=session_id or (parent.session_id if parent else None),
        purpose=purpose,
        path=(parent.path.parent if parent else get_astraclaw_home() / "usage") / f"{run_id}.jsonl",
    )
    _append(run, "run_started", purpose=purpose)
    token = _current_run.set(run)
    started = perf_counter()
    error_type = None
    try:
        yield run
    except BaseException as exc:
        run.status = "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit, GeneratorExit)) else "failed"
        error_type = type(exc).__name__
        raise
    finally:
        _current_run.reset(token)
        _append(run, "run_finished", purpose=purpose, status=run.status,
                duration_seconds=perf_counter() - started, error_type=error_type)


def tracked_run(purpose):
    """Give each conversation/manual compaction a fresh, nestable run ID."""
    def decorate(fn):
        @wraps(fn)
        def wrapped(self, *args, **kwargs):
            run_purpose = "delegate" if purpose == "conversation" and self.system_prompt_override is not None else purpose
            with run_scope(run_purpose, kwargs.get("current_session_id")) as run:
                self.last_usage_run = run
                return fn(self, *args, **kwargs)
        return wrapped
    return decorate


def _usage_dict(usage):
    if isinstance(usage, dict):
        return usage
    if isinstance(usage, SimpleNamespace):
        return {key: _usage_dict(value) if isinstance(value, SimpleNamespace) else value
                for key, value in vars(usage).items()}
    if callable(getattr(usage, "model_dump", None)):
        value = usage.model_dump(mode="json")
        return value if isinstance(value, dict) else None
    return None


def _count(value):
    return value if type(value) is int and value >= 0 else None


def normalize_usage(raw):
    """OpenAI-compatible counts; detail fields are subsets, never added to totals."""
    raw = raw or {}
    prompt_details = raw.get("prompt_tokens_details") or {}
    output_details = raw.get("completion_tokens_details") or {}
    counts = {
        "input_tokens": _count(raw.get("prompt_tokens")),
        "output_tokens": _count(raw.get("completion_tokens")),
        "total_tokens": _count(raw.get("total_tokens")),
        "cached_input_tokens": _count(prompt_details.get("cached_tokens")) if isinstance(prompt_details, dict) else None,
        "reasoning_tokens": _count(output_details.get("reasoning_tokens")) if isinstance(output_details, dict) else None,
    }
    status = "reported" if counts["input_tokens"] is not None and counts["output_tokens"] is not None else (
        "partial" if any(value is not None for value in counts.values()) else "missing"
    )
    return counts, status


@dataclass
class RequestEvidence:
    raw_usage: dict | None = None
    response_id: str | None = None
    response_model: str | None = None
    service_tier: str | None = None
    finish_reason: str | None = None
    status: str = "completed"

    def observe(self, response):
        usage = _usage_dict(getattr(response, "usage", None))
        if usage is not None:
            # Stream usage is a request snapshot, not a delta to sum per chunk.
            self.raw_usage = usage
        for field_name, source in (("response_id", "id"), ("response_model", "model"),
                                   ("service_tier", "service_tier")):
            value = getattr(response, source, None)
            if isinstance(value, str):
                setattr(self, field_name, value)
        choices = getattr(response, "choices", None)
        if isinstance(choices, list) and choices:
            reason = getattr(choices[0], "finish_reason", None)
            if isinstance(reason, str):
                self.finish_reason = reason


@contextmanager
def request_scope(provider, model, *, purpose, attempt=1, operation_id=None):
    """One explicit SDK invocation. Start-only records remain unknown after a crash."""
    if _current_run.get() is None:
        with run_scope(purpose):
            with request_scope(provider, model, purpose=purpose, attempt=attempt,
                               operation_id=operation_id) as evidence:
                yield evidence
        return
    run = _current_run.get()
    request_id = uuid4().hex
    identity = dict(request_id=request_id, operation_id=operation_id or request_id,
                    provider=provider, model=model, purpose=purpose, attempt=attempt)
    _append(run, "request_started", **identity)
    evidence = RequestEvidence()
    started = perf_counter()
    error_type = None
    http_status = None
    try:
        yield evidence
    except BaseException as exc:
        evidence.status = "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit, GeneratorExit)) else "failed"
        error_type = type(exc).__name__
        value = getattr(exc, "status_code", None)
        http_status = value if type(value) is int else None
        raise
    finally:
        duration = perf_counter() - started
        counts, usage_status = normalize_usage(evidence.raw_usage)
        cost = estimate_cost(provider, model, evidence.raw_usage,
                             response_model=evidence.response_model,
                             service_tier=evidence.service_tier,
                             request_status=evidence.status)
        _append(run, "request_finished", **identity, status=evidence.status,
                duration_seconds=duration,
                usage_status=usage_status, raw_usage=evidence.raw_usage, **counts,
                response_id=evidence.response_id, response_model=evidence.response_model,
                service_tier=evidence.service_tier, finish_reason=evidence.finish_reason,
                error_type=error_type, http_status=http_status, **cost)


def mark_run_status(status):
    run = _current_run.get()
    if run is not None:
        run.status = status


def context_with_run(context, run):
    """Attach a completed conversation as parent for the later title thread."""
    if isinstance(run, UsageRun):
        context.run(_current_run.set, run)
    return context
