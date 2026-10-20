import json

import pytest

from astra_claw import constants
from astra_claw.tools.file_tools import read_file, write_file


@pytest.fixture(autouse=True)
def _fence_tmp_path(tmp_path):
    """Point the workspace fence at tmp_path for every file-tool test."""
    constants.set_workspace_fence(tmp_path)
    yield
    constants._workspace_fence = None


class TestFileTools:
    def test_read_existing_file(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("Hello, world!", encoding="utf-8")

        result = json.loads(read_file({"path": str(f)}))
        assert result["content"] == "Hello, world!"
        assert "error" not in result

    def test_read_nonexistent_file(self):
        result = json.loads(read_file({"path": "/no/such/file/ever.txt"}))
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_read_no_path(self):
        result = json.loads(read_file({}))
        assert "error" in result
        assert "No path" in result["error"]

    def test_read_empty_path(self):
        result = json.loads(read_file({"path": ""}))
        assert "error" in result

    def test_read_multiline_file(self, tmp_path):
        f = tmp_path / "multi.txt"
        content = "line1\nline2\nline3\n"
        f.write_text(content, encoding="utf-8")

        result = json.loads(read_file({"path": str(f)}))
        assert result["content"] == content

    def test_read_pages_without_skipping_or_modifying_text(self, tmp_path):
        f = tmp_path / "pages.txt"
        content = "".join(f"line {i}\n" for i in range(1, 4002))
        f.write_text(content, encoding="utf-8")
        pages = []
        offset = 1
        while offset is not None:
            result = json.loads(read_file({"path": str(f), "offset": offset}))
            assert result["lines_read"] <= 2000
            pages.append(result["content"])
            offset = result["next_offset"]
        assert "".join(pages) == content
        assert len(pages) == 3

    def test_explicit_offset_limit_and_cap(self, tmp_path):
        f = tmp_path / "lines.txt"
        f.write_text("".join(f"{i}\n" for i in range(1, 2101)), encoding="utf-8")
        result = json.loads(read_file({"path": str(f), "offset": 100, "limit": 200}))
        assert result["content"].splitlines() == [str(i) for i in range(100, 300)]
        assert result["next_offset"] == 300
        capped = json.loads(read_file({"path": str(f), "limit": 9999}))
        assert capped["lines_read"] == 2000
        assert capped["next_offset"] == 2001

    @pytest.mark.parametrize("field,value", [
        ("offset", 0), ("offset", -1), ("offset", True), ("offset", "1"),
        ("limit", 0), ("limit", -1), ("limit", False), ("limit", 1.5),
    ])
    def test_invalid_page_parameters(self, field, value):
        assert "error" in json.loads(read_file({"path": "unused", field: value}))

    def test_empty_and_past_end_reads(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")
        for offset in (1, 100):
            result = json.loads(read_file({"path": str(f), "offset": offset}))
            assert result["content"] == ""
            assert result["lines_read"] == 0
            assert result["next_offset"] is None

    def test_write_new_file(self, tmp_path):
        f = tmp_path / "hello.txt"

        result = json.loads(write_file({"path": str(f), "content": "Hello"}))

        assert "error" not in result
        assert f.read_text(encoding="utf-8") == "Hello"

    def test_write_overwrites_existing_file(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("Old", encoding="utf-8")

        result = json.loads(write_file({"path": str(f), "content": "New"}))

        assert "error" not in result
        assert f.read_text(encoding="utf-8") == "New"

    def test_write_creates_parent_directories(self, tmp_path):
        f = tmp_path / "nested" / "dir" / "hello.txt"

        result = json.loads(write_file({"path": str(f), "content": "Made"}))

        assert "error" not in result
        assert f.exists()
        assert f.read_text(encoding="utf-8") == "Made"

    def test_write_no_path(self):
        result = json.loads(write_file({"content": "Hello"}))
        assert "error" in result
        assert "No path" in result["error"]

    def test_write_no_content(self):
        result = json.loads(write_file({"path": "some.txt"}))
        assert "error" in result
        assert "No content" in result["error"]

    def test_write_blocked_path(self, tmp_path):
        f = tmp_path / ".env"

        result = json.loads(write_file({"path": str(f), "content": "SECRET=1"}))

        assert "error" in result
        assert "Write denied" in result["error"]
        assert not f.exists()
