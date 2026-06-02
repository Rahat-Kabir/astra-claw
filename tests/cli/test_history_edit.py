from astra_claw.cli.history_edit import find_last_user_message, truncate_for_retry


def test_find_last_user_message_returns_latest():
    history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": "a2"},
    ]

    idx, text = find_last_user_message(history)

    assert idx == 2
    assert text == "second"


def test_find_last_user_message_empty_history():
    assert find_last_user_message([]) == (None, None)


def test_find_last_user_message_skips_blank_user_content():
    history = [
        {"role": "user", "content": "   "},
        {"role": "assistant", "content": "a1"},
    ]

    assert find_last_user_message(history) == (None, None)


def test_truncate_for_retry_removes_last_turn():
    history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": "a2"},
    ]

    truncated, text = truncate_for_retry(history)

    assert text == "second"
    assert truncated == history[:2]


def test_truncate_for_retry_includes_tool_messages_in_removed_tail():
    history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "run tests"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call1", "function": {"name": "shell", "arguments": "{}"}}],
        },
        {"role": "tool", "content": "ok", "tool_call_id": "call1"},
        {"role": "assistant", "content": "done"},
    ]

    truncated, text = truncate_for_retry(history)

    assert text == "run tests"
    assert len(truncated) == 2
    assert truncated[-1]["role"] == "assistant"


def test_truncate_for_retry_only_user_message():
    history = [{"role": "user", "content": "solo"}]

    truncated, text = truncate_for_retry(history)

    assert text == "solo"
    assert truncated == []
