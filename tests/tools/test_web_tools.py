import json

from astra_claw.tools import web_tools
from astra_claw.tools.registry import registry


class TestWebToolRegistration:
    def test_web_tools_hidden_without_api_key(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)

        defs = registry.get_definitions(enabled_toolsets={"web"})

        assert defs == []

    def test_web_tools_visible_with_api_key(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

        defs = registry.get_definitions(enabled_toolsets={"web"})
        names = [entry["function"]["name"] for entry in defs]

        assert names == ["web_search", "web_extract"]


class TestWebSearchTool:
    def test_search_normalizes_tavily_results(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
        calls = []

        def fake_post(endpoint, payload):
            calls.append((endpoint, payload))
            return {
                "results": [
                    {"title": "Alpha", "url": "https://example.com/a", "content": "desc a"},
                    {"title": "Beta", "url": "https://example.com/b", "content": "desc b"},
                ]
            }

        monkeypatch.setattr(web_tools, "_tavily_post", fake_post)

        result = json.loads(web_tools.web_search({"query": "test query", "max_results": 9}))

        assert calls == [(
            "search",
            {
                "query": "test query",
                "max_results": 5,
                "include_raw_content": False,
                "include_images": False,
            },
        )]
        assert result == {
            "success": True,
            "results": [
                {
                    "title": "Alpha",
                    "url": "https://example.com/a",
                    "description": "desc a",
                    "position": 1,
                },
                {
                    "title": "Beta",
                    "url": "https://example.com/b",
                    "description": "desc b",
                    "position": 2,
                },
            ],
        }

    def test_search_requires_query(self):
        result = json.loads(web_tools.web_search({}))
        assert result["success"] is False
        assert "No query provided" in result["error"]

    def test_search_timeout_returns_error(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
        monkeypatch.setattr(web_tools, "_tavily_post", lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError()))

        result = json.loads(web_tools.web_search({"query": "slow"}))

        assert result["success"] is False
        assert "timed out" in result["error"]


class TestWebExtractTool:
    def test_extract_normalizes_and_truncates_results(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
        calls = []
        long_content = "x" * 9000

        def fake_post(endpoint, payload):
            calls.append((endpoint, payload))
            return {
                "results": [
                    {
                        "url": "https://example.com/a",
                        "title": "Doc A",
                        "raw_content": long_content,
                    }
                ],
                "failed_results": [
                    {
                        "url": "https://example.com/b",
                        "error": "fetch failed",
                    }
                ],
            }

        monkeypatch.setattr(web_tools, "_tavily_post", fake_post)

        result = json.loads(
            web_tools.web_extract(
                {
                    "urls": ["https://example.com/a", "https://example.com/b"],
                    "format": "text",
                    "extract_depth": "advanced",
                }
            )
        )

        assert calls == [(
            "extract",
            {
                "urls": ["https://example.com/a", "https://example.com/b"],
                "extract_depth": "advanced",
                "format": "text",
                "include_images": False,
                "include_favicon": False,
            },
        )]
        assert result["success"] is True
        assert len(result["results"]) == 2
        assert result["results"][0]["url"] == "https://example.com/a"
        assert result["results"][0]["title"] == "Doc A"
        assert result["results"][0]["truncated"] is True
        assert len(result["results"][0]["content"]) == 8000
        assert result["results"][0]["error"] is None
        assert result["results"][1] == {
            "url": "https://example.com/b",
            "title": "",
            "content": "",
            "truncated": False,
            "error": "fetch failed",
        }

    def test_extract_rejects_invalid_scheme(self):
        result = json.loads(web_tools.web_extract({"urls": ["file:///etc/passwd"]}))

        assert result["success"] is False
        assert "URL must use http or https" in result["error"]

    def test_extract_rejects_too_many_urls(self):
        urls = [f"https://example.com/{i}" for i in range(6)]

        result = json.loads(web_tools.web_extract({"urls": urls}))

        assert result["success"] is False
        assert "at most 5 URLs" in result["error"]

    def test_extract_requires_non_empty_url_list(self):
        result = json.loads(web_tools.web_extract({"urls": []}))

        assert result["success"] is False
        assert "non-empty list" in result["error"]
