import json

import pytest

from astra_claw import constants
from astra_claw.tools.patch_tool import patch_file
from astra_claw.tools.registry import registry


@pytest.fixture(autouse=True)
def _fence_tmp_path(tmp_path):
    """Point the workspace fence at tmp_path for every patch-tool test."""
    constants.set_workspace_fence(tmp_path)
    yield
    constants._workspace_fence = None


class TestPatchTool:
    def test_unique_replacement_succeeds(self, tmp_path):
        f = tmp_path / "sample.txt"
        f.write_text("hello world\n", encoding="utf-8")

        result = json.loads(
            patch_file(
                {
                    "path": str(f),
                    "old_text": "hello",
                    "new_text": "hi",
                }
            )
        )

        assert result["success"] is True
        assert result["replacements"] == 1
        assert f.read_text(encoding="utf-8") == "hi world\n"
        assert "-hello world" in result["diff"]
        assert "+hi world" in result["diff"]

    def test_delete_with_empty_new_text_succeeds(self, tmp_path):
        f = tmp_path / "sample.txt"
        f.write_text("keep\nremove me\nkeep too\n", encoding="utf-8")

        result = json.loads(
            patch_file(
                {
                    "path": str(f),
                    "old_text": "remove me\n",
                    "new_text": "",
                }
            )
        )

        assert result["success"] is True
        assert f.read_text(encoding="utf-8") == "keep\nkeep too\n"

    def test_no_match_fails_without_modifying_file(self, tmp_path):
        f = tmp_path / "sample.txt"
        f.write_text("abc\n", encoding="utf-8")

        result = json.loads(
            patch_file(
                {
                    "path": str(f),
                    "old_text": "xyz",
                    "new_text": "123",
                }
            )
        )

        assert "error" in result
        assert "not found" in result["error"]
        assert f.read_text(encoding="utf-8") == "abc\n"

    def test_multiple_matches_fail_by_default(self, tmp_path):
        f = tmp_path / "sample.txt"
        f.write_text("foo foo foo\n", encoding="utf-8")

        result = json.loads(
            patch_file(
                {
                    "path": str(f),
                    "old_text": "foo",
                    "new_text": "bar",
                }
            )
        )

        assert "error" in result
        assert "matched 3 times" in result["error"]
        assert f.read_text(encoding="utf-8") == "foo foo foo\n"

    def test_replace_all_replaces_multiple_matches(self, tmp_path):
        f = tmp_path / "sample.txt"
        f.write_text("foo foo foo\n", encoding="utf-8")

        result = json.loads(
            patch_file(
                {
                    "path": str(f),
                    "old_text": "foo",
                    "new_text": "bar",
                    "replace_all": True,
                }
            )
        )

        assert result["success"] is True
        assert result["replacements"] == 3
        assert f.read_text(encoding="utf-8") == "bar bar bar\n"

    def test_empty_old_text_fails(self, tmp_path):
        f = tmp_path / "sample.txt"
        f.write_text("abc\n", encoding="utf-8")

        result = json.loads(
            patch_file(
                {
                    "path": str(f),
                    "old_text": "",
                    "new_text": "x",
                }
            )
        )

        assert "error" in result
        assert "old_text" in result["error"]
        assert f.read_text(encoding="utf-8") == "abc\n"

    def test_missing_new_text_fails(self, tmp_path):
        f = tmp_path / "sample.txt"
        f.write_text("abc\n", encoding="utf-8")

        result = json.loads(
            patch_file(
                {
                    "path": str(f),
                    "old_text": "abc",
                }
            )
        )

        assert "error" in result
        assert "new_text" in result["error"]
        assert f.read_text(encoding="utf-8") == "abc\n"

    def test_workspace_escape_is_blocked(self, tmp_path, monkeypatch):
        inside = tmp_path / "inside"
        inside.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("old\n", encoding="utf-8")
        monkeypatch.chdir(inside)
        constants.set_workspace_fence(inside)

        result = json.loads(
            patch_file(
                {
                    "path": "../outside.txt",
                    "old_text": "old",
                    "new_text": "new",
                }
            )
        )

        assert "error" in result
        assert "escapes workspace fence" in result["error"]
        assert outside.read_text(encoding="utf-8") == "old\n"

    def test_protected_path_is_blocked(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("SECRET=old\n", encoding="utf-8")

        result = json.loads(
            patch_file(
                {
                    "path": str(f),
                    "old_text": "old",
                    "new_text": "new",
                }
            )
        )

        assert "error" in result
        assert "protected path" in result["error"]
        assert f.read_text(encoding="utf-8") == "SECRET=old\n"

    def test_registry_exposes_patch_schema(self):
        names = {
            entry["function"]["name"]
            for entry in registry.get_definitions(enabled_toolsets={"filesystem"})
        }

        assert "patch" in names
