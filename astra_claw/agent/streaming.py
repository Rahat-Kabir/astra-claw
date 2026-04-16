"""Stream-collection helper for the agent loop.

Iterates the OpenAI-compatible streaming response, accumulates content and
tool-call deltas, and fires an optional on_thinking(active) callback when
the first meaningful delta arrives.
"""

from __future__ import annotations

import sys
from typing import Any, Callable, Dict, List, Optional, Tuple


def collect_stream_response(
    client: Any,
    route: Dict[str, str],
    messages: List[Dict[str, Any]],
    *,
    tools: Optional[List[Dict[str, Any]]] = None,
    stream_writer: Optional[Callable[[str], None]] = None,
    on_thinking: Optional[Callable[[bool], None]] = None,
) -> Tuple[str, Optional[List[Dict[str, Any]]], bool]:
    """Iterate a single streamed completion and return its shape.

    Returns (full_content, tool_calls_list_or_None, has_meaningful_output).
    Raises the SDK's error on failure; the caller handles fallback.
    """
    kwargs: Dict[str, Any] = {
        "model": route["model"],
        "messages": messages,
        "stream": True,
    }
    if tools:
        kwargs["tools"] = tools

    if on_thinking is not None:
        on_thinking(True)
    thinking_stopped = False

    content_parts: List[str] = []
    tool_calls_acc: Dict[int, Dict[str, Any]] = {}
    has_meaningful_output = False

    try:
        stream = client.chat.completions.create(**kwargs)
        for chunk in stream:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            if delta.content:
                if not thinking_stopped and on_thinking is not None:
                    on_thinking(False)
                    thinking_stopped = True
                has_meaningful_output = True
                content_parts.append(delta.content)
                if not tool_calls_acc:
                    if stream_writer is not None:
                        stream_writer(delta.content)
                    else:
                        sys.stdout.write(delta.content)
                        sys.stdout.flush()

            if delta.tool_calls:
                if not thinking_stopped and on_thinking is not None:
                    on_thinking(False)
                    thinking_stopped = True
                has_meaningful_output = True
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index if tc_delta.index is not None else 0
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {
                            "id": tc_delta.id or "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    entry = tool_calls_acc[idx]
                    if tc_delta.id:
                        entry["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            entry["function"]["name"] += tc_delta.function.name
                        if tc_delta.function.arguments:
                            entry["function"]["arguments"] += tc_delta.function.arguments
    finally:
        if not thinking_stopped and on_thinking is not None:
            on_thinking(False)

    full_content = "".join(content_parts)
    tool_calls_list = (
        [tool_calls_acc[i] for i in sorted(tool_calls_acc)] if tool_calls_acc else None
    )
    return full_content, tool_calls_list, has_meaningful_output


def is_context_overflow_error(exc: Exception) -> bool:
    haystack = f"{exc.__class__.__name__} {exc}".lower()
    markers = (
        "context length",
        "maximum context length",
        "too many tokens",
        "prompt is too long",
        "context window",
    )
    return any(marker in haystack for marker in markers)
