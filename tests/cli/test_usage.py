from types import SimpleNamespace

from astra_claw.agent.context_compactor import CompactionConfig, ContextCompactor
from astra_claw.cli.usage import build_usage_snapshot


class FakeAgent:
    def __init__(self):
        self.primary_route = {"provider": "openai", "model": "gpt-test"}
        self.compression_enabled = True
        self.compactor = ContextCompactor(
            CompactionConfig(
                context_window=200,
                threshold_ratio=0.50,
                reserve_tokens=10,
                keep_first_n=2,
                keep_last_n=2,
                max_passes=1,
            ),
            tool_schemas=[],
        )
        self.memory_store = SimpleNamespace(
            memory_entries=["note one"],
            user_entries=[],
            memory_char_limit=2200,
            user_char_limit=1375,
        )

    def get_system_prompt_text(self) -> str:
        return "system prompt"


def test_build_usage_snapshot_empty_history():
    agent = FakeAgent()
    snapshot = build_usage_snapshot(
        agent=agent,
        session_id="sess-1",
        history=[],
        session_meta={"compactions": 0},
        heartbeat={
            "stream_tokens": 0,
            "tools": 0,
            "elapsed_secs": None,
            "in_progress": False,
        },
    )

    assert snapshot.session_id == "sess-1"
    assert snapshot.message_count == 0
    assert snapshot.estimated_total >= snapshot.estimated_system
    assert snapshot.would_compact is False
    assert snapshot.memory_chars == len("note one")


def test_build_usage_snapshot_would_compact():
    agent = FakeAgent()
    big_history = [{"role": "user", "content": "x" * 800} for _ in range(6)]

    snapshot = build_usage_snapshot(
        agent=agent,
        session_id="sess-2",
        history=big_history,
        session_meta={"compactions": 2, "last_compacted_at": "2026-06-01"},
        heartbeat={
            "stream_tokens": 100,
            "tools": 1,
            "elapsed_secs": 5.0,
            "in_progress": True,
        },
    )

    assert snapshot.would_compact is True
    assert snapshot.compactions == 2
    assert snapshot.turn_in_progress is True
    assert snapshot.estimated_total == (
        snapshot.estimated_system
        + snapshot.estimated_tools
        + snapshot.estimated_history
    )
