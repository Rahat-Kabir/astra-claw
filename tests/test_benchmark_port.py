"""One-task pilot: independent grading and mock process runs, never paid calls."""

import json

import pytest

from scripts.benchmark_port import TASK, permitted_call, run_benchmark, run_checker, usage_summary


def test_broken_fixture_fails_independent_checker(tmp_path):
    (tmp_path / "ports.py").write_bytes((TASK / "fixture" / "ports.py").read_bytes())
    grade = run_checker(tmp_path)
    assert grade["grade_status"] == "graded" and grade["passed"] is False
    assert grade["checks"]["valid_range"] is True
    assert grade["checks"]["rejects_out_of_range"] is False
    assert grade["checks"]["rejects_other_types"] is False


def test_mock_full_pipeline_and_fresh_reset(tmp_path):
    first = tmp_path / "first"
    report = run_benchmark(first)
    assert report["verified_success"] is True
    assert report["grade"]["passed"] is True
    assert report["mode"] == "mock" and report["usage_origin"] == "synthetic"
    assert report["tool_calls"] == 2
    assert report["usage"]["requests_started"] == report["usage"]["requests_finished"] == 3
    assert report["usage"]["input_tokens"] == 300
    assert report["usage"]["estimated_cost_usd"] is None
    manifest = json.loads((first / "manifest.json").read_text())
    assert "api_key" not in manifest["config"]["model"]
    assert manifest["config"]["model"]["max_completion_tokens"] == 2048
    assert manifest["config"]["model"]["fallback_provider"] is None
    assert manifest["config"]["memory"]["enabled"] is False
    assert manifest["tools"] == ["patch", "read_file", "write_file"]
    for field in ("fixture_sha256", "checker_sha256", "harness_sha256", "prompt_sha256", "runner_sha256"):
        assert len(manifest[field]) == 64
    second = run_benchmark(tmp_path / "second", mode="mock-noop")
    assert second["execution_status"] == "completed"
    assert second["grade"]["passed"] is False
    assert second["verified_success"] is False
    with pytest.raises(FileExistsError):
        run_benchmark(first)


def test_worker_timeout_does_not_claim_success(tmp_path):
    report = run_benchmark(tmp_path / "timeout", timeout=0.001)
    assert report["execution_status"] == "timeout"
    assert report["verified_success"] is False
    assert report["usage"]["estimated_cost_usd"] is None


@pytest.mark.parametrize("source,reason", [
    ("raise RuntimeError('broken checker')", "checker_process_failed"),
    ("print('not json')", "invalid_checker_result"),
    ("import time; time.sleep(20)", "checker_timeout"),
])
def test_checker_failure_is_unknown_not_task_failure(tmp_path, source, reason):
    checker = tmp_path / "checker.py"
    checker.write_text(source)
    grade = run_checker(tmp_path, checker=checker, timeout=0.3)
    assert grade == {"grade_status": "error", "passed": None, "reason": reason}


def test_syntax_error_is_a_task_failure(tmp_path):
    (tmp_path / "ports.py").write_text("def validate_port(")
    grade = run_checker(tmp_path)
    assert grade["grade_status"] == "graded" and grade["passed"] is False
    assert grade["evidence"] == "SyntaxError"


def test_tool_policy_blocks_checker_and_other_tools(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def call(name, path):
        return {"function": {"name": name, "arguments": json.dumps({"path": path})}}

    assert permitted_call(call("patch", "ports.py"), tmp_path)
    assert not permitted_call(call("read_file", str(TASK / "check.py")), tmp_path)
    assert not permitted_call(call("write_file", "../outside.py"), tmp_path)
    assert not permitted_call(call("shell", "ports.py"), tmp_path)
    assert not permitted_call(call("delegate", "ports.py"), tmp_path)
    assert not permitted_call({}, tmp_path)


def test_usage_coverage_does_not_hide_unmatched_or_corrupt_records(tmp_path):
    rows = [{"event": "request_started", "request_id": "one"},
            {"event": "request_finished", "request_id": "one", "input_tokens": 10,
             "output_tokens": 2, "cost_status": "estimated", "estimated_cost_usd": 0.01},
            {"event": "request_started", "request_id": "two"}]
    path = tmp_path / "ledger.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + '\n{"partial":')
    result = usage_summary(tmp_path)
    assert result["unmatched_starts"] == 1
    assert result["recorded_cost_usd"] == 0.01
    assert result["estimated_cost_usd"] is None and result["input_tokens"] is None
    assert result["reported_input_tokens"] == 10
    assert result["ledger_issues"] == ["invalid_jsonl"]
