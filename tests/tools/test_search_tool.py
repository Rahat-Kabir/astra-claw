import json

from astra_claw.tools.search_tool import search_files


class TestSearchTool:
    def test_search_content_finds_match(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("Hello world\nSecond line\n", encoding="utf-8")

        result = json.loads(
            search_files(
                {
                    "pattern": "hello",
                    "target": "content",
                    "path": str(tmp_path),
                }
            )
        )

        assert "matches" in result
        assert result["total_count"] >= 1
        assert any("Hello world" in match or "hello" in match.lower() for match in result["matches"])

    def test_search_content_no_matches(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("Hello world\n", encoding="utf-8")

        result = json.loads(
            search_files(
                {
                    "pattern": "missing-text",
                    "target": "content",
                    "path": str(tmp_path),
                }
            )
        )

        assert result["matches"] == []
        assert "No matches" in result["message"]

    def test_search_files_finds_filename(self, tmp_path):
        f = tmp_path / "report.txt"
        f.write_text("data", encoding="utf-8")

        result = json.loads(
            search_files(
                {
                    "pattern": "*.txt",
                    "target": "files",
                    "path": str(tmp_path),
                }
            )
        )

        assert "files" in result
        assert result["total_count"] >= 1
        assert any("report.txt" in path for path in result["files"])

    def test_search_files_no_results(self, tmp_path):
        result = json.loads(
            search_files(
                {
                    "pattern": "*.md",
                    "target": "files",
                    "path": str(tmp_path),
                }
            )
        )

        assert result["files"] == []
        assert "No files found" in result["message"]

    def test_search_invalid_path_returns_error(self):
        result = json.loads(
            search_files(
                {
                    "pattern": "hello",
                    "target": "content",
                    "path": "Z:/definitely/not/real/path",
                }
            )
        )

        assert "error" in result
        assert "Path not found" in result["error"]

    def test_search_missing_pattern_returns_error(self):
        result = json.loads(search_files({}))
        assert "error" in result
        assert "No pattern" in result["error"]

    def test_search_content_with_file_glob(self, tmp_path):
        py_file = tmp_path / "app.py"
        txt_file = tmp_path / "notes.txt"

        py_file.write_text("target_text = True\n", encoding="utf-8")
        txt_file.write_text("target_text in txt\n", encoding="utf-8")

        result = json.loads(
            search_files(
                {
                    "pattern": "target_text",
                    "target": "content",
                    "path": str(tmp_path),
                    "file_glob": "*.py",
                }
            )
        )

        assert "matches" in result
        assert result["total_count"] >= 1
        assert all(".py" in match.lower() for match in result["matches"])
