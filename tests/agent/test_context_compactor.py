from astra_claw.agent.context_compactor import (
    SUMMARY_PREFIX,
    CompactionConfig,
    ContextCompactor,
)


def _message(role, content, **extra):
    message = {"role": role, "content": content}
    message.update(extra)
    return message


def _compactor(**overrides):
    config = CompactionConfig(
        context_window=overrides.get("context_window", 120),
        threshold_ratio=overrides.get("threshold_ratio", 0.50),
        reserve_tokens=overrides.get("reserve_tokens", 10),
        keep_first_n=overrides.get("keep_first_n", 2),
        keep_last_n=overrides.get("keep_last_n", 2),
        max_passes=overrides.get("max_passes", 2),
        summary_model=None,
    )
    return ContextCompactor(
        config,
        tool_schemas=overrides.get("tool_schemas", []),
    )


def test_should_compact_false_below_threshold():
    compactor = _compactor()
    history = [
        _message("user", "hi"),
        _message("assistant", "hello"),
        _message("user", "bye"),
        _message("assistant", "later"),
    ]

    assert not compactor.should_compact(system_prompt="short", history=history)


def test_should_compact_true_above_threshold():
    compactor = _compactor()
    history = [
        _message("user", "a" * 120),
        _message("assistant", "b" * 120),
        _message("user", "c" * 120),
        _message("assistant", "d" * 120),
        _message("user", "e" * 120),
        _message("assistant", "f" * 120),
    ]

    assert compactor.should_compact(system_prompt="short", history=history)


def test_compact_keeps_first_and_last_windows():
    compactor = _compactor()
    history = [
        _message("user", "keep-first-user"),
        _message("assistant", "keep-first-assistant"),
        _message("user", "middle-user-1"),
        _message("assistant", "middle-assistant-1"),
        _message("user", "middle-user-2"),
        _message("assistant", "middle-assistant-2"),
        _message("user", "keep-last-user"),
        _message("assistant", "keep-last-assistant"),
    ]

    outcome = compactor.compact(
        system_prompt="prompt",
        history=history,
        summarize_fn=lambda messages, previous: "summary",
        force=True,
    )

    assert outcome.did_compact
    assert outcome.messages[:2] == history[:2]
    assert outcome.messages[-2:] == history[-2:]
    assert outcome.messages[2]["content"].startswith(SUMMARY_PREFIX)


def test_compact_does_not_split_assistant_tool_pairs():
    compactor = _compactor(keep_first_n=1, keep_last_n=2)
    history = [
        _message("user", "first"),
        _message(
            "assistant",
            "",
            tool_calls=[{"id": "call1", "function": {"name": "read_file", "arguments": "{}"}}],
        ),
        _message("tool", "tool-result", tool_call_id="call1"),
        _message("assistant", "middle answer"),
        _message("user", "tail-user"),
        _message("assistant", "tail-assistant"),
    ]

    outcome = compactor.compact(
        system_prompt="prompt",
        history=history,
        summarize_fn=lambda messages, previous: "summary",
        force=True,
    )

    roles = [message["role"] for message in outcome.messages]
    assert roles[:3] == ["user", "assistant", "tool"]


def test_compact_reuses_previous_summary():
    compactor = _compactor(keep_first_n=1, keep_last_n=1, max_passes=1)
    history = [
        _message("user", "first"),
        _message("assistant", f"{SUMMARY_PREFIX}\nold summary"),
        _message("user", "middle"),
        _message("assistant", "middle reply"),
        _message("assistant", "tail"),
    ]
    calls = []

    outcome = compactor.compact(
        system_prompt="prompt",
        history=history,
        summarize_fn=lambda messages, previous: calls.append(previous) or "new summary",
        force=True,
    )

    assert outcome.did_compact
    assert calls == ["old summary"]
    assert outcome.summary_text == "new summary"


def test_estimate_request_tokens_includes_tool_schemas():
    without_tools = _compactor()
    with_tools = _compactor(tool_schemas=[{"type": "function", "function": {"name": "search"}}])
    history = [_message("user", "hi"), _message("assistant", "hello")]

    assert with_tools.estimate_request_tokens(system_prompt="prompt", history=history) > without_tools.estimate_request_tokens(
        system_prompt="prompt",
        history=history,
    )


def test_compact_returns_original_history_when_summary_is_not_smaller():
    compactor = _compactor()
    history = [
        _message("user", "keep-first-user"),
        _message("assistant", "keep-first-assistant"),
        _message("user", "x"),
        _message("assistant", "y"),
        _message("user", "keep-last-user"),
        _message("assistant", "keep-last-assistant"),
    ]

    outcome = compactor.compact(
        system_prompt="prompt",
        history=history,
        summarize_fn=lambda messages, previous: "z" * 500,
        force=True,
    )

    assert not outcome.did_compact
    assert outcome.messages == history
