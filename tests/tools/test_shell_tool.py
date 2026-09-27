import json

import pytest

from astra_claw.tools.shell_tool import (
    classify_command_risk,
    run_command,
    set_approval_callback,
)


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        ("pip install requests", "Python packages"),
        ("python -m pip install requests", "Python packages"),
        (r".\venv\Scripts\python.exe -m pip install requests", "Python packages"),
        ("uv pip install openpyxl", "Python packages"),
        ("uv run --with pillow script.py", "runs Python packages"),
        ("uv run --with-requirements requirements.txt script.py", "runs Python packages"),
        ("uv tool install ruff", "Python tools"),
        ("uvx ruff check", "Python tool"),
        ("npm install", "JavaScript packages"),
        ("pnpm add react", "JavaScript packages"),
        ("yarn install", "JavaScript packages"),
        ("bun add zod", "JavaScript packages"),
        ("npx create-next-app demo", "JavaScript package"),
        ("pnpm dlx create-vite demo", "JavaScript package"),
        ("winget install Git.Git", "system packages"),
        ("choco install git", "system packages"),
        ("scoop install git", "system packages"),
        ("echo ready; uv pip install openpyxl", "Python packages"),
    ],
)
def test_classify_command_risk_detects_package_mutation(command, reason):
    assert reason in classify_command_risk(command)


@pytest.mark.parametrize(
    "command",
    [
        "uv run pytest",
        "npm test",
        "pnpm test",
        'git commit -m "document pip install behavior"',
    ],
)
def test_classify_command_risk_leaves_normal_commands_unflagged(command):
    assert classify_command_risk(command) is None


class TestShellTool:
    def teardown_method(self):
        set_approval_callback(None)

    def test_run_command_requires_command(self):
        result = json.loads(run_command({}))
        assert "error" in result
        assert "No command" in result["error"]

    def test_run_safe_command_success(self):
        result = json.loads(run_command({"command": "echo hello"}))
        assert result["exit_code"] == 0
        assert "hello" in result["output"].lower()

    def test_run_command_captures_stderr(self):
        result = json.loads(
            run_command(
                {
                    "command": 'python -c "import sys; sys.stderr.write(\'boom\')"',
                    "timeout": 5,
                }
            )
        )
        assert "output" in result
        assert "boom" in result["output"].lower()

    def test_run_command_timeout(self):
        result = json.loads(
            run_command(
                {
                    "command": 'python -c "import time; time.sleep(2)"',
                    "timeout": 1,
                }
            )
        )
        assert "error" in result
        assert "timed out" in result["error"].lower()

    def test_dangerous_command_blocked_without_callback(self):
        set_approval_callback(None)

        result = json.loads(run_command({"command": "rm -rf testdir"}))

        assert "error" in result
        assert "blocked" in result["error"].lower()

    def test_dangerous_command_denied_by_callback(self):
        set_approval_callback(lambda command, reason: False)

        result = json.loads(run_command({"command": "rm -rf testdir"}))

        assert "error" in result
        assert "denied" in result["error"].lower()

    def test_dangerous_command_allowed_by_callback(self):
        calls = []

        def allow(command, reason):
            calls.append((command, reason))
            return True

        set_approval_callback(allow)

        result = json.loads(run_command({"command": "rm -rf testdir"}))

        assert len(calls) == 1
        assert calls[0][0] == "rm -rf testdir"
        assert "error" not in result
        assert "exit_code" in result

    def test_package_install_denial_prevents_subprocess(self, monkeypatch):
        subprocess_called = False

        def unexpected_run(*args, **kwargs):
            nonlocal subprocess_called
            subprocess_called = True
            raise AssertionError("subprocess.run must not be called")

        monkeypatch.setattr(
            "astra_claw.tools.shell_tool.subprocess.run",
            unexpected_run,
        )
        set_approval_callback(lambda command, reason: False)

        result = json.loads(run_command({"command": "uv pip install openpyxl"}))

        assert "denied" in result["error"].lower()
        assert subprocess_called is False

    def test_package_install_passes_reason_to_approval(self, monkeypatch):
        approval_calls = []

        def deny(command, reason):
            approval_calls.append((command, reason))
            return False

        monkeypatch.setattr(
            "astra_claw.tools.shell_tool.subprocess.run",
            lambda *args, **kwargs: pytest.fail("denied command was executed"),
        )
        set_approval_callback(deny)

        run_command({"command": "uv run --with pillow script.py"})

        assert approval_calls == [
            (
                "uv run --with pillow script.py",
                "downloads and runs Python packages",
            )
        ]
