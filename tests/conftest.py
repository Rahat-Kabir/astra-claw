"""Keep all test-generated user data, including usage ledgers, out of the real home."""

import pytest


@pytest.fixture(autouse=True)
def isolated_astraclaw_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRACLAW_HOME", str(tmp_path / "astraclaw"))
