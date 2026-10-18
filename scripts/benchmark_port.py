"""One fixed port-validation task. Defaults to a no-cost mock plumbing check.

Run: python scripts/benchmark_port.py --mode mock
Live: python scripts/benchmark_port.py --mode live
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace as NS
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TASK = ROOT / "benchmarks" / "port_validation"
TOOLS = {"read_file", "write_file", "patch"}


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def usage_summary(directory):
    starts, finishes, issues = {}, {}, []
    for path in sorted(directory.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                issues.append("invalid_jsonl")
                continue
            if not isinstance(row, dict):
                issues.append("invalid_record")
                continue
            event, request_id = row.get("event"), row.get("request_id")
            target = starts if event == "request_started" else finishes if event == "request_finished" else None
            if target is not None:
                if not isinstance(request_id, str):
                    issues.append("missing_request_id")
                    continue
                if request_id in target:
                    issues.append("duplicate_request_event")
                target[request_id] = row
    rows = list(finishes.values())
    unmatched = len(starts.keys() - finishes.keys())
    if finishes.keys() - starts.keys():
        issues.append("finish_without_start")
    priced = [r for r in rows if r.get("cost_status") == "estimated"]
    recorded = sum(r["estimated_cost_usd"] for r in priced)
    complete = bool(starts) and not issues and not unmatched
    result = {"requests_started": len(starts), "requests_finished": len(finishes),
              "unmatched_starts": unmatched, "ledger_issues": issues,
              "requests_priced": len(priced), "recorded_cost_usd": recorded,
              "estimated_cost_usd": recorded if complete and len(priced) == len(starts) else None}
    for name in ("input_tokens", "output_tokens"):
        known = [r[name] for r in rows if type(r.get(name)) is int]
        result[f"reported_{name}"] = sum(known)
        result[name] = sum(known) if complete and len(known) == len(starts) else None
    return result


def run_checker(workspace, *, checker=None, timeout=5):
    checker = checker or TASK / "check.py"
    # Do not pass model credentials to code executed during grading.
    env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH")
           if key in os.environ}
    try:
        result = subprocess.run([sys.executable, "-I", str(checker), str(workspace / "ports.py")],
                                env=env, cwd=workspace, capture_output=True, text=True,
                                timeout=timeout, check=False)
        if result.returncode:
            return {"grade_status": "error", "passed": None, "reason": "checker_process_failed"}
        grade = json.loads(result.stdout)
        if (grade.get("grade_status") != "graded" or type(grade.get("passed")) is not bool
                or not isinstance(grade.get("checks"), dict)):
            raise ValueError("Invalid checker result")
        return grade
    except subprocess.TimeoutExpired:
        return {"grade_status": "error", "passed": None, "reason": "checker_timeout"}
    except (json.JSONDecodeError, ValueError, AttributeError):
        return {"grade_status": "error", "passed": None, "reason": "invalid_checker_result"}


def mock_client(mode, workspace):
    """Synthetic model events exercise the real loop, tools, ledger, and checker."""
    original = (workspace / "ports.py").read_text(encoding="utf-8")
    fixed = original.replace("not isinstance(value, int)", "type(value) is not int").replace(
        "0 <= value <= 65536", "1 <= value <= 65535")

    def stream(name=None, args=None):
        tool = NS(index=0, id=uuid4().hex, function=NS(name=name, arguments=json.dumps(args))) if name else None
        yield NS(id="synthetic", model="mock-port-fix", usage=None, choices=[NS(
            delta=NS(content=None if name else "Done.", tool_calls=[tool] if tool else None),
            finish_reason="tool_calls" if name else "stop")])
        yield NS(id="synthetic", model="mock-port-fix", choices=[], usage={
            "prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
            "prompt_tokens_details": {"cached_tokens": 0}})

    streams = iter([stream("read_file", {"path": "ports.py"}),
                    stream("patch", {"path": "ports.py", "old_text": original, "new_text": fixed}),
                    stream()] if mode == "mock" else [stream()])
    return NS(chat=NS(completions=NS(create=lambda **kwargs: next(streams))))


def permitted_call(call, workspace):
    try:
        args = json.loads(call["function"]["arguments"])
        return (call["function"]["name"] in TOOLS
                and Path(args.get("path", "")).resolve() == workspace / "ports.py")
    except (KeyError, ValueError, TypeError, AttributeError, OSError):
        return False


def worker(directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    workspace = directory / "workspace"
    os.chdir(workspace)
    from astra_claw.constants import set_workspace_fence
    from astra_claw.agent import loop

    set_workspace_fence(workspace)
    config = manifest["config"]
    config["model"]["api_key"] = os.environ.get("ASTRA_BENCH_API_KEY", "")
    if manifest["mode"] != "live":
        fake = mock_client(manifest["mode"], workspace)
        loop.create_client = lambda *args, **kwargs: fake

    original_executor = loop.execute_tool_calls

    def bounded_tools(calls, **kwargs):
        # This policy is local to the worker process. Keep the checker outside
        # the agent's tool access, including unrestricted read_file/search/shell.
        results = []
        for call in calls:
            if permitted_call(call, workspace):
                results.extend(original_executor([call], **kwargs))
            else:
                results.append({"role": "tool", "tool_call_id": call["id"],
                                "content": json.dumps({"error": "Benchmark permits file tools on ports.py only"})})
        return results

    loop.execute_tool_calls = bounded_tools
    agent = loop.AstraAgent(config=config)
    agent.tools = [tool for tool in agent.tools if tool["function"]["name"] in TOOLS]
    try:
        _, messages = agent.run_conversation(manifest["prompt"], stream_writer=lambda _: None)
        output = {"execution_status": agent.last_usage_run.status,
                  "root_run_id": agent.last_usage_run.root_run_id,
                  "tool_calls": sum(m["role"] == "tool" for m in messages)}
    except Exception as exc:
        output = {"execution_status": "failed", "error_type": type(exc).__name__}
    save(directory / "execution.json", output)


def run_benchmark(directory, *, mode="mock", timeout=90, max_turns=6):
    from astra_claw.agent.prompt_builder import DEFAULT_IDENTITY
    from astra_claw.config import load_config
    from astra_claw.llm import resolve_api_key

    if timeout <= 0 or max_turns <= 0:
        raise ValueError("Timeout and max turns must be positive")
    key = ""
    if mode == "live":
        route = load_config()["model"]
        provider = route.get("provider", "openai")
        key = resolve_api_key(provider, route)
        if not key:
            raise RuntimeError("No model credentials configured")
        model = route["default"]
    else:
        provider, model = "mock", "mock-port-fix"
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    workspace, home = directory / "workspace", directory / "home"
    workspace.mkdir()
    home.mkdir()
    (home / "SOUL.md").write_text(DEFAULT_IDENTITY, encoding="utf-8")
    shutil.copyfile(TASK / "fixture" / "ports.py", workspace / "ports.py")
    prompt = (TASK / "prompt.md").read_text(encoding="utf-8")
    config = {"model": {"provider": provider, "default": model, "fallback_provider": None,
                         "max_completion_tokens": 2048},
              "agent": {"max_turns": max_turns}, "compression": {"enabled": False},
              "memory": {"enabled": False, "user_profile_enabled": False},
              "tools": {"enabled_toolsets": ["filesystem"]}, "session": {"auto_title": False}}
    harness_bytes = b"".join(str(p.relative_to(ROOT)).encode() + p.read_bytes()
                             for p in sorted((ROOT / "astra_claw").rglob("*.py")))
    manifest = {"task_id": "port_validation", "task_version": 1, "mode": mode,
                "usage_origin": "provider" if mode == "live" else "synthetic",
                "prompt": prompt, "prompt_sha256": digest(prompt.encode()),
                "fixture_sha256": digest((workspace / "ports.py").read_bytes()),
                "checker_sha256": digest((TASK / "check.py").read_bytes()),
                "runner_sha256": digest(Path(__file__).read_bytes()),
                "harness_sha256": digest(harness_bytes), "config": config,
                "tools": sorted(TOOLS), "timeout_seconds": timeout, "python_version": sys.version}
    save(directory / "manifest.json", manifest)
    env = {**os.environ, "ASTRACLAW_HOME": str(home), "ASTRA_BENCH_API_KEY": key}
    started = time.perf_counter()
    with (directory / "worker_stdout.log").open("w", encoding="utf-8") as out, \
         (directory / "worker_stderr.log").open("w", encoding="utf-8") as err:
        try:
            process = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                      "--worker", str(directory)], env=env, stdout=out,
                                     stderr=err, timeout=timeout, check=False)
            execution = json.loads((directory / "execution.json").read_text(encoding="utf-8")) if (
                process.returncode == 0 and (directory / "execution.json").exists()) else {
                    "execution_status": "failed", "reason": "worker_process_failed"}
        except subprocess.TimeoutExpired:
            execution = {"execution_status": "timeout"}
    elapsed = time.perf_counter() - started
    grade = run_checker(workspace)
    if digest((TASK / "check.py").read_bytes()) != manifest["checker_sha256"]:
        grade = {"grade_status": "error", "passed": None, "reason": "checker_changed"}
    result = {"task_id": "port_validation", "task_version": 1, "mode": mode,
              "usage_origin": manifest["usage_origin"], **execution, "duration_seconds": elapsed,
              "grade": grade, "verified_success": execution["execution_status"] == "completed"
              and grade["grade_status"] == "graded" and grade["passed"],
              "usage": usage_summary(home / "usage")}
    save(directory / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("mock", "mock-noop", "live"), default="mock")
    parser.add_argument("--output", type=Path, help="New result directory; existing directories are rejected")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--max-turns", type=int, default=6)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker.resolve())
        return 0
    from astra_claw.constants import get_astraclaw_home
    directory = args.output or get_astraclaw_home() / "benchmarks" / "port_validation" / uuid4().hex
    result = run_benchmark(directory, mode=args.mode, timeout=args.timeout, max_turns=args.max_turns)
    print(json.dumps(result, indent=2))
    print(f"Result: {directory.resolve() / 'result.json'}")
    return 0 if result["verified_success"] else 1


if __name__ == "__main__":
    sys.exit(main())
