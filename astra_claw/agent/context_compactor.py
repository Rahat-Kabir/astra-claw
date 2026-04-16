"""Persistent conversation compaction helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


SUMMARY_PREFIX = "[CONTEXT COMPACTION]"


@dataclass(frozen=True)
class CompactionConfig:
    context_window: int
    threshold_ratio: float
    reserve_tokens: int
    keep_first_n: int
    keep_last_n: int
    max_passes: int
    summary_model: Optional[str] = None


@dataclass(frozen=True)
class CompactionOutcome:
    did_compact: bool
    messages: List[Dict[str, Any]]
    summary_text: str
    estimated_tokens_before: int
    estimated_tokens_after: int
    dropped_messages: int
    passes: int


class ContextCompactor:
    """Compact the middle of a conversation while protecting the edges."""

    def __init__(
        self,
        config: CompactionConfig,
        tool_schemas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.config = config
        self.tool_schemas = list(tool_schemas or [])
        self._tool_schema_tokens = _estimate_json_tokens(self.tool_schemas)

    def estimate_request_tokens(
        self,
        *,
        system_prompt: str,
        history: List[Dict[str, Any]],
        pending_user_message: Optional[str] = None,
    ) -> int:
        total = _estimate_text_tokens(system_prompt) + self._tool_schema_tokens
        total += sum(_estimate_message_tokens(message) for message in history)
        if pending_user_message:
            total += _estimate_message_tokens({"role": "user", "content": pending_user_message})
        return total

    def should_compact(
        self,
        *,
        system_prompt: str,
        history: List[Dict[str, Any]],
        pending_user_message: Optional[str] = None,
        force: bool = False,
    ) -> bool:
        if not history:
            return False
        start, end = _find_middle_slice(
            history,
            keep_first_n=self.config.keep_first_n,
            keep_last_n=self.config.keep_last_n,
        )
        if start >= end:
            return False
        if force:
            return True

        estimated = self.estimate_request_tokens(
            system_prompt=system_prompt,
            history=history,
            pending_user_message=pending_user_message,
        )
        threshold_budget = max(
            0,
            int(self.config.context_window * self.config.threshold_ratio) - self.config.reserve_tokens,
        )
        return estimated > threshold_budget

    def compact(
        self,
        *,
        system_prompt: str,
        history: List[Dict[str, Any]],
        summarize_fn: Callable[[List[Dict[str, Any]], Optional[str]], str],
        force: bool = False,
    ) -> CompactionOutcome:
        original = list(history)
        current = list(history)
        estimated_before = self.estimate_request_tokens(system_prompt=system_prompt, history=current)
        latest_summary = ""
        passes = 0
        total_dropped = 0

        if not self.should_compact(system_prompt=system_prompt, history=current, force=force):
            return CompactionOutcome(
                did_compact=False,
                messages=current,
                summary_text="",
                estimated_tokens_before=estimated_before,
                estimated_tokens_after=estimated_before,
                dropped_messages=0,
                passes=0,
            )

        while passes < self.config.max_passes:
            start, end = _find_middle_slice(
                current,
                keep_first_n=self.config.keep_first_n,
                keep_last_n=self.config.keep_last_n,
            )
            if start >= end:
                break

            middle_messages = current[start:end]
            previous_summary = _extract_previous_summary(middle_messages)
            messages_to_summarize = [message for message in middle_messages if not _is_summary_message(message)]
            if not messages_to_summarize and previous_summary is None:
                break

            latest_summary = summarize_fn(messages_to_summarize, previous_summary).strip()
            if not latest_summary:
                break

            current = current[:start] + [_build_summary_message(latest_summary)] + current[end:]
            total_dropped += max(0, len(middle_messages) - 1)
            passes += 1

            if not self.should_compact(system_prompt=system_prompt, history=current):
                break

        estimated_after = self.estimate_request_tokens(system_prompt=system_prompt, history=current)
        did_compact = passes > 0
        if did_compact and estimated_after >= estimated_before:
            return CompactionOutcome(
                did_compact=False,
                messages=original,
                summary_text="",
                estimated_tokens_before=estimated_before,
                estimated_tokens_after=estimated_before,
                dropped_messages=0,
                passes=0,
            )
        return CompactionOutcome(
            did_compact=did_compact,
            messages=current,
            summary_text=latest_summary,
            estimated_tokens_before=estimated_before,
            estimated_tokens_after=estimated_after,
            dropped_messages=total_dropped if did_compact else 0,
            passes=passes,
        )


def _estimate_text_tokens(text: Any) -> int:
    if not text:
        return 0
    return max(1, (len(str(text)) + 3) // 4)


def _estimate_json_tokens(value: Any) -> int:
    if not value:
        return 0
    return _estimate_text_tokens(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _estimate_message_tokens(message: Dict[str, Any]) -> int:
    return _estimate_json_tokens(message) + 4


def _find_middle_slice(messages: List[Dict[str, Any]], *, keep_first_n: int, keep_last_n: int) -> tuple[int, int]:
    start = _align_start_forward(messages, keep_first_n)
    end = _align_end_backward(messages, len(messages) - keep_last_n)
    return start, max(start, end)


def _align_start_forward(messages: List[Dict[str, Any]], idx: int) -> int:
    if idx <= 0:
        return 0
    if idx >= len(messages):
        return len(messages)

    message = messages[idx]
    if message.get("role") == "tool":
        while idx < len(messages) and messages[idx].get("role") == "tool":
            idx += 1
        return idx

    if message.get("role") == "assistant" and message.get("tool_calls"):
        idx += 1
        while idx < len(messages) and messages[idx].get("role") == "tool":
            idx += 1
        return idx

    return idx


def _align_end_backward(messages: List[Dict[str, Any]], idx: int) -> int:
    if idx <= 0:
        return 0
    if idx >= len(messages):
        return len(messages)

    previous = messages[idx - 1]
    if previous.get("role") == "tool":
        while idx > 0 and messages[idx - 1].get("role") == "tool":
            idx -= 1
        if idx > 0:
            assistant = messages[idx - 1]
            if assistant.get("role") == "assistant" and assistant.get("tool_calls"):
                idx -= 1
        return idx

    if previous.get("role") == "assistant" and previous.get("tool_calls"):
        return idx - 1

    return idx


def _is_summary_message(message: Dict[str, Any]) -> bool:
    return (
        message.get("role") == "assistant"
        and isinstance(message.get("content"), str)
        and message["content"].startswith(SUMMARY_PREFIX)
    )


def _extract_previous_summary(messages: List[Dict[str, Any]]) -> Optional[str]:
    for message in messages:
        if _is_summary_message(message):
            content = str(message.get("content", ""))
            return content[len(SUMMARY_PREFIX) :].strip()
    return None


def _build_summary_message(summary_text: str) -> Dict[str, Any]:
    return {
        "role": "assistant",
        "content": f"{SUMMARY_PREFIX}\n{summary_text.strip()}",
    }
