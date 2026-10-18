"""CLI-run measurement checks. All model calls are mocked; no paid requests."""

import json
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from openai.types import CompletionUsage

from astra_claw import llm
from astra_claw.agent.loop import AstraAgent
from astra_claw.agent.streaming import collect_stream_response
from astra_claw.agent.title_generator import maybe_auto_title
from astra_claw.session import create_session
from astra_claw.usage_ledger import normalize_usage, request_scope, run_scope


def records(_monkeypatch, event=None):
    # Read the same configured home as production, never Path.home().
    from astra_claw.constants import get_astraclaw_home
    rows = [json.loads(line) for path in (get_astraclaw_home() / "usage").glob("*.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines()]
    return [row for row in rows if event is None or row["event"] == event]


def chunk(text=None, *, usage=None, finish=None):
    choices = [] if text is None and finish is None else [
        NS(delta=NS(content=text, tool_calls=None), finish_reason=finish)
    ]
    return NS(choices=choices, usage=usage, id="response-1", model="resolved-model")


def usage(prompt=12, output=3):
    return CompletionUsage(prompt_tokens=prompt, completion_tokens=output,
                           total_tokens=prompt + output,
                           prompt_tokens_details={"cached_tokens": 4},
                           completion_tokens_details={"reasoning_tokens": 1})


def client(*streams):
    return NS(chat=NS(completions=NS(create=Mock(side_effect=list(streams)))))


def config(**extra):
    return {"model": {"provider": "openai", "default": "test-model", **extra},
            "memory": {"enabled": False}, "compression": {"enabled": False}}


def agent_with(monkeypatch, fake, **extra):
    monkeypatch.setattr("astra_claw.agent.loop.create_client", lambda *a, **k: fake)
    return AstraAgent(config(**extra))


def test_usage_only_chunk_is_saved_once_and_not_summed(monkeypatch):
    fake = client([chunk("answer"), chunk(finish="stop"), chunk(usage=usage()), chunk(usage=usage())])
    text, _, _ = collect_stream_response(fake, {"provider": "openai", "model": "alias"},
                                         [], stream_writer=lambda _: None)
    assert text == "answer"
    row, = records(monkeypatch, "request_finished")
    assert row["usage_status"] == "reported"
    assert (row["input_tokens"], row["output_tokens"], row["total_tokens"]) == (12, 3, 15)
    assert row["cached_input_tokens"] == 4
    assert row["reasoning_tokens"] == 1
    assert row["raw_usage"]["prompt_tokens_details"]["cached_tokens"] == 4
    assert row["model"] == "alias" and row["response_model"] == "resolved-model"
    assert row["response_id"] == "response-1"
    assert fake.chat.completions.create.call_args.kwargs["stream_options"] == {"include_usage": True}
    assert row["status"] == "completed"
    assert row["finish_reason"] == "stop"


@pytest.mark.parametrize("raw,status,expected", [
    (None, "missing", None),
    ({"prompt_tokens": 8}, "partial", 8),
    ({"prompt_tokens": 0, "completion_tokens": 0}, "reported", 0),
    ({"prompt_tokens": -1, "completion_tokens": True}, "missing", None),
    ({"prompt_tokens": "12", "completion_tokens": 2}, "partial", None),
])
def test_missing_and_invalid_values_are_not_zero(raw, status, expected):
    counts, actual = normalize_usage(raw)
    assert actual == status
    assert counts["input_tokens"] == expected
    assert counts["cached_input_tokens"] is None


def test_missing_usage_is_distinct_from_completed_execution(monkeypatch):
    fake = client([chunk("answer", finish="stop")])
    agent = agent_with(monkeypatch, fake)
    agent.run_conversation("private prompt", stream_writer=lambda _: None, current_session_id="session-1")
    row, = records(monkeypatch, "request_finished")
    assert row["status"] == "completed"
    assert row["usage_status"] == "missing"
    assert row["input_tokens"] is None and row["raw_usage"] is None
    assert row["session_id"] == "session-1"
    assert row["run_id"] == agent.last_usage_run.run_id
    assert "private prompt" not in json.dumps(records(monkeypatch))


def test_stream_without_finish_is_incomplete(monkeypatch):
    agent = agent_with(monkeypatch, client([chunk("partial")]))
    agent.run_conversation("task", stream_writer=lambda _: None)
    assert records(monkeypatch, "request_finished")[0]["status"] == "interrupted"
    assert records(monkeypatch, "run_finished")[0]["status"] == "incomplete"


def test_interrupted_stream_keeps_observed_usage_and_closes(monkeypatch):
    class BrokenStream:
        closed = False

        def __iter__(self):
            yield chunk(usage=usage())
            raise KeyboardInterrupt("secret prompt must not enter logs")

        def close(self):
            self.closed = True

    stream = BrokenStream()
    with pytest.raises(KeyboardInterrupt):
        collect_stream_response(client(stream), {"provider": "openai", "model": "m"}, [])
    row, = records(monkeypatch, "request_finished")
    assert stream.closed
    assert row["status"] == "interrupted"
    assert row["input_tokens"] == 12
    assert row["error_type"] == "KeyboardInterrupt"
    assert "secret prompt" not in json.dumps(records(monkeypatch))


def test_fallback_attempts_share_operation_and_run(monkeypatch):
    failure = RuntimeError("Connection error with secret")
    first = client(failure)
    second = client([chunk("ok", finish="stop"), chunk(usage=usage())])
    monkeypatch.setattr("astra_claw.agent.loop.create_client",
                        lambda provider, **kw: first if provider == "openai" else second)
    agent = AstraAgent(config(fallback_provider="openrouter", fallback_model="other"))
    agent.run_conversation("task", stream_writer=lambda _: None)
    rows = sorted(records(monkeypatch, "request_finished"), key=lambda r: r["attempt"])
    assert len(rows) == 2
    assert [r["attempt"] for r in rows] == [1, 2]
    assert [r["status"] for r in rows] == ["failed", "completed"]
    assert rows[0]["usage_status"] == "missing"
    assert rows[0]["operation_id"] == rows[1]["operation_id"]
    assert rows[0]["run_id"] == rows[1]["run_id"]
    assert rows[0]["request_id"] != rows[1]["request_id"]
    assert "secret" not in json.dumps(rows)


def test_auth_failure_is_logged_without_fallback(monkeypatch):
    error = RuntimeError("unauthorized")
    error.status_code = 401
    agent = agent_with(monkeypatch, client(error), fallback_provider="openrouter")
    with pytest.raises(RuntimeError):
        agent.run_conversation("task")
    row, = records(monkeypatch, "request_finished")
    assert row["http_status"] == 401
    assert records(monkeypatch, "run_finished")[0]["status"] == "failed"


def test_nonstream_compatibility_retry_has_separate_requests(monkeypatch):
    response = NS(usage=usage(), choices=[NS(message=NS(content="Title"))])
    fake = client(RuntimeError("unsupported max_completion_tokens"), response)
    monkeypatch.setattr(llm, "create_client", lambda *a, **k: fake)
    assert llm.complete_once([], provider="openai", model="m", purpose="title") == "Title"
    rows = sorted(records(monkeypatch, "request_finished"), key=lambda r: r["attempt"])
    assert len(rows) == 2
    assert rows[0]["operation_id"] == rows[1]["operation_id"]
    assert [row["status"] for row in rows] == ["failed", "completed"]
    assert all(row["purpose"] == "title" for row in rows)


def test_compaction_is_attributed_to_conversation(monkeypatch):
    agent = agent_with(monkeypatch, client([chunk("summary", finish="stop"), chunk(usage=usage())]))
    with run_scope("conversation") as parent:
        assert agent._summarize_for_compaction([{"role": "user", "content": "old"}]) == "summary"
    row, = records(monkeypatch, "request_finished")
    assert row["purpose"] == "compaction" and row["run_id"] == parent.run_id


def test_delegate_child_uses_separate_run_with_parent_link(monkeypatch):
    from astra_claw.tools.delegate_tool import delegate_tool
    agent_with(monkeypatch, client([chunk("child report", finish="stop")]))
    with run_scope("conversation", session_id="parent-session") as parent:
        result = json.loads(delegate_tool(goal="inspect", parent_config=config(),
                                          parent_session_id="parent-session"))
    assert result["status"] == "completed"
    row, = records(monkeypatch, "request_finished")
    assert row["run_id"] != parent.run_id
    assert row["parent_run_id"] == parent.run_id
    assert row["root_run_id"] == parent.run_id
    assert row["purpose"] == "delegate"


def test_title_thread_links_to_finished_parent(monkeypatch):
    session = create_session()
    response = NS(usage=usage(), choices=[NS(message=NS(content="Session Title"))])
    monkeypatch.setattr(llm, "create_client", lambda *a, **k: client(response))
    with run_scope("conversation", session_id=session) as parent:
        pass
    thread = maybe_auto_title(session, "explain the parser code", "Here it is", user_msg_count=1,
                              provider="openai", model="m", usage_run=parent)
    thread.join(timeout=3)
    assert not thread.is_alive()
    row, = records(monkeypatch, "request_finished")
    assert row["root_run_id"] == parent.run_id
    assert row["session_id"] == session and row["purpose"] == "title"
    assert row["parent_run_id"] == parent.run_id


def test_starts_exist_before_network_and_context_is_reset(monkeypatch):
    with run_scope("conversation") as parent:
        with request_scope("openai", "m", purpose="conversation"):
            assert len(records(monkeypatch, "request_started")) == 1
            assert not records(monkeypatch, "request_finished")
    with run_scope("conversation") as other:
        assert other.parent_run_id is None and other.run_id != parent.run_id


def test_ledger_write_failure_blocks_request(monkeypatch):
    from astra_claw.constants import get_astraclaw_home
    home = get_astraclaw_home()
    home.mkdir(parents=True)
    (home / "usage").write_text("not a directory")
    fake = client([])
    with pytest.raises(OSError):
        collect_stream_response(fake, {"provider": "openai", "model": "m"}, [])
    fake.chat.completions.create.assert_not_called()


def test_each_conversation_has_new_run_and_request_ids(monkeypatch):
    agent = agent_with(monkeypatch, client([chunk("one", finish="stop")],
                                           [chunk("two", finish="stop")]))
    agent.run_conversation("first", stream_writer=lambda _: None)
    first_run = agent.last_usage_run.run_id
    agent.run_conversation("second", stream_writer=lambda _: None)
    rows = records(monkeypatch, "request_finished")
    assert len({r["request_id"] for r in rows}) == 2
    assert len({r["run_id"] for r in rows}) == 2
    assert agent.last_usage_run.run_id != first_run
    assert all(r["parent_run_id"] is None for r in rows)


def test_manual_compaction_run_carries_session(monkeypatch):
    agent = agent_with(monkeypatch, client())
    agent.compact_history([], current_session_id="manual-session")
    row, = records(monkeypatch, "run_started")
    assert row["purpose"] == "manual_compaction"
    assert row["session_id"] == "manual-session"
    assert not records(monkeypatch, "request_started")


def test_partial_usage_keeps_raw_evidence(monkeypatch):
    fake = client([chunk("done", finish="stop"), chunk(usage={"prompt_tokens": 5})])
    collect_stream_response(fake, {"provider": "openai", "model": "m"}, [],
                            stream_writer=lambda _: None)
    row, = records(monkeypatch, "request_finished")
    assert row["usage_status"] == "partial"
    assert row["input_tokens"] == 5 and row["output_tokens"] is None
    assert row["raw_usage"] == {"prompt_tokens": 5}


def test_optional_output_limit_reaches_sdk(monkeypatch):
    fake = client([chunk("done", finish="stop")])
    agent = agent_with(monkeypatch, fake, max_completion_tokens=2048)
    agent.run_conversation("task", stream_writer=lambda _: None)
    assert fake.chat.completions.create.call_args.kwargs["max_completion_tokens"] == 2048


def test_parallel_threads_do_not_share_run_context(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    def work(_):
        with run_scope("conversation") as run:
            with request_scope("openai", "m", purpose="conversation"):
                pass
            return run.run_id

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(work, range(12)))
    rows = records(monkeypatch, "request_finished")
    assert len(rows) == 12 and len(set(ids)) == 12
    assert {r["run_id"] for r in rows} == set(ids)
    assert all(r["parent_run_id"] is None for r in rows)
