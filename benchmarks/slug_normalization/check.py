"""Independent contract checks, run after the worker exits."""

import importlib.util
import itertools
import json
from pathlib import Path
import sys


def expected(text):
    # Character state machine, independent of a regex-based repair.
    result = []
    separator = False
    for char in text.lower():
        if "a" <= char <= "z" or "0" <= char <= "9":
            if separator and result:
                result.append("-")
            result.append(char)
            separator = False
        else:
            separator = True
    return "".join(result)


def grade(path):
    checks = dict.fromkeys(("loads", "examples", "character_combinations", "long_input"), False)
    try:
        spec = importlib.util.spec_from_file_location("candidate_slug", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = module.slugify
        checks["loads"] = callable(fn)

        def matches(text):
            result = fn(text)
            return type(result) is str and result == expected(text)

        checks["examples"] = all(matches(text) for text in (
            "", "Hello World", "  A___B!! ", "---", "ABC123", "a\tb\nc",
            "café déjà vu", "東京", "İSTANBUL", "a\x00b", "a😀b", "already-slug"))
        checks["character_combinations"] = all(matches("".join(chars))
            for size in range(5) for chars in itertools.product("aZ0 -_é", repeat=size))
        checks["long_input"] = matches("!!A__9  " * 2000)
    except Exception as exc:
        return {"grade_status": "graded", "passed": False, "checks": checks,
                "evidence": type(exc).__name__}
    return {"grade_status": "graded", "passed": all(checks.values()), "checks": checks}


if __name__ == "__main__":
    print(json.dumps(grade(Path(sys.argv[1]))))
