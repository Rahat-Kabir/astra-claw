"""Independent contract checks, run after the worker exits."""

import importlib.util
import json
from pathlib import Path
import sys


def grade(path):
    checks = dict.fromkeys(("loads", "schedule", "large_attempts", "rejects_invalid"), False)
    try:
        spec = importlib.util.spec_from_file_location("candidate_retry", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = module.retry_delay
        checks["loads"] = callable(fn)
        checks["schedule"] = all(type(result := fn(attempt)) is int and result == expected
                                 for attempt, expected in enumerate((1, 2, 4, 8, 16, 30, 30, 30)))
        checks["large_attempts"] = all(type(result := fn(value)) is int and result == 30
                                       for value in (31, 1000, 10**100))

        def rejected(value):
            try:
                fn(value)
            except ValueError:
                return True
            return False

        checks["rejects_invalid"] = all(rejected(value) for value in
            (-1, -10**100, True, False, None, "2", 2.0, b"2", [], {}))
    except Exception as exc:
        return {"grade_status": "graded", "passed": False, "checks": checks,
                "evidence": type(exc).__name__}
    return {"grade_status": "graded", "passed": all(checks.values()), "checks": checks}


if __name__ == "__main__":
    print(json.dumps(grade(Path(sys.argv[1]))))
