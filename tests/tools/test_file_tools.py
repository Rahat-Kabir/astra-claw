import json

from astra_claw.tools.file_tools import read_file, write_file


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
