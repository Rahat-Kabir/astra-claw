"""Pure helpers for the /usage context panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional


@dataclass(frozen=True)
class UsageSnapshot:
    provider: str
    model: str
    session_id: str
    message_count: int

    context_window: int
    estimated_total: int
    estimated_system: int
    estimated_tools: int
    estimated_history: int
    threshold_budget: int
    headroom: int
    context_percent: int
    would_compact: bool
    compression_enabled: bool
    compactions: int
    last_compacted_at: Optional[str]

    memory_enabled: bool
    memory_chars: Optional[int]
    memory_limit: Optional[int]
    memory_entries: Optional[int]
    user_chars: Optional[int]
    user_limit: Optional[int]
    user_entries: Optional[int]

    last_turn_stream_tokens: int
    last_turn_tools: int
    last_turn_elapsed_secs: Optional[float]
    turn_in_progress: bool


def _percent(used: int, total: int) -> int:
    if total <= 0:
        return 0
    return max(0, min(100, round(used / total * 100)))


def _memory_char_count(entries: List[str]) -> int:
    if not entries:
        return 0
    return len("\n§\n".join(entries))


def build_usage_snapshot(
    *,
    agent: Any,
    session_id: str,
    history: List[dict],
    session_meta: Mapping[str, Any],
    heartbeat: Mapping[str, Any],
) -> UsageSnapshot:
    """Build a usage snapshot from live REPL state. Pure — no I/O, no Rich."""
    route = getattr(agent, "primary_route", None) or {}
    provider = str(route.get("provider", "") or "unknown")
    model = str(route.get("model", "") or "unknown")

    system_prompt = agent.get_system_prompt_text()
    compactor = agent.compactor
    compression_enabled = bool(getattr(agent, "compression_enabled", True))

    estimated_system, estimated_tools, estimated_history, estimated_total = (
        compactor.estimate_request_breakdown(
            system_prompt=system_prompt,
            history=history,
        )
    )

    context_window = compactor.config.context_window
    threshold_budget = compactor.threshold_budget
    headroom = max(0, threshold_budget - estimated_total)

    would_compact = False
    if compression_enabled and history:
        would_compact = compactor.should_compact(
            system_prompt=system_prompt,
            history=history,
        )

    memory_store = getattr(agent, "memory_store", None)
    memory_enabled = memory_store is not None
    memory_chars = memory_limit = memory_entries = None
    user_chars = user_limit = user_entries = None
    if memory_store is not None:
        memory_chars = _memory_char_count(memory_store.memory_entries)
        memory_limit = memory_store.memory_char_limit
        memory_entries = len(memory_store.memory_entries)
        user_chars = _memory_char_count(memory_store.user_entries)
        user_limit = memory_store.user_char_limit
        user_entries = len(memory_store.user_entries)

    return UsageSnapshot(
        provider=provider,
        model=model,
        session_id=session_id,
        message_count=len(history),
        context_window=context_window,
        estimated_total=estimated_total,
        estimated_system=estimated_system,
        estimated_tools=estimated_tools,
        estimated_history=estimated_history,
        threshold_budget=threshold_budget,
        headroom=headroom,
        context_percent=_percent(estimated_total, context_window),
        would_compact=would_compact,
        compression_enabled=compression_enabled,
        compactions=int(session_meta.get("compactions", 0) or 0),
        last_compacted_at=session_meta.get("last_compacted_at"),
        memory_enabled=memory_enabled,
        memory_chars=memory_chars,
        memory_limit=memory_limit,
        memory_entries=memory_entries,
        user_chars=user_chars,
        user_limit=user_limit,
        user_entries=user_entries,
        last_turn_stream_tokens=int(heartbeat.get("stream_tokens", 0) or 0),
        last_turn_tools=int(heartbeat.get("tools", 0) or 0),
        last_turn_elapsed_secs=heartbeat.get("elapsed_secs"),
        turn_in_progress=bool(heartbeat.get("in_progress")),
    )
