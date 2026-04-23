import json

from astra_claw.tools.shell_tool import run_command, set_approval_callback


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
