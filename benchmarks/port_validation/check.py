"""Independent checker. Run only after the agent process has exited."""

import importlib.util
import json
from pathlib import Path
import sys


def grade(path):
    checks = {"loads": False, "valid_range": False, "rejects_out_of_range": False,
              "rejects_other_types": False}
    try:
        spec = importlib.util.spec_from_file_location("candidate_ports", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = module.validate_port
        checks["loads"] = callable(fn)
    except Exception as exc:
        return {"grade_status": "graded", "passed": False, "checks": checks,
                "evidence": type(exc).__name__}

    def rejected(value):
        try:
            fn(value)
        except ValueError:
            return True
        return False

    try:
        checks["valid_range"] = all(type(result := fn(value)) is int and result == value
                                    for value in range(1, 65536))
        checks["rejects_out_of_range"] = all(rejected(value) for value in
                                              (-10**20, -1, 0, 65536, 65537, 10**20))
        checks["rejects_other_types"] = all(rejected(value) for value in
                                              (True, False, None, "80", b"80", 80.0, [], {}))
    except Exception as exc:
        return {"grade_status": "graded", "passed": False, "checks": checks,
                "evidence": type(exc).__name__}
    return {"grade_status": "graded", "passed": all(checks.values()), "checks": checks}


if __name__ == "__main__":
    print(json.dumps(grade(Path(sys.argv[1]))))
