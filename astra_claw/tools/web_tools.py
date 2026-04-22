"""Web tools backed by Tavily.

V1 scope:
- ``web_search`` for search result metadata
- ``web_extract`` for page content extraction

Both tools are synchronous, require ``TAVILY_API_KEY``, and always return JSON
strings so they fit the registry contract.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .registry import registry

_TAVILY_BASE_URL = "https://api.tavily.com"
_REQUEST_TIMEOUT_SECONDS = 30
_MAX_SEARCH_RESULTS = 5
_MAX_EXTRACT_URLS = 5
_MAX_CONTENT_CHARS = 8000


def _has_tavily_api_key() -> bool:
    return bool(os.getenv("TAVILY_API_KEY", "").strip())


def _error(message: str) -> str:
    return json.dumps({"success": False, "error": message}, ensure_ascii=False)


def _validate_http_url(url: str) -> Optional[str]:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return "URL must use http or https"
    if not parsed.netloc:
        return "URL must include a hostname"
    return None


def _truncate_content(content: str) -> tuple[str, bool]:
    if len(content) <= _MAX_CONTENT_CHARS:
        return content, False
    return content[:_MAX_CONTENT_CHARS], True


def _tavily_post(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        raise ValueError("TAVILY_API_KEY environment variable not set")

    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url=f"{_TAVILY_BASE_URL}/{endpoint.lstrip('/')}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    with urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def web_search(args: dict) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return _error("No query provided")

    max_results = args.get("max_results", _MAX_SEARCH_RESULTS)
    try:
        max_results = int(max_results)
    except (TypeError, ValueError):
        return _error("max_results must be an integer")
    if max_results < 1:
        return _error("max_results must be at least 1")
    max_results = min(max_results, _MAX_SEARCH_RESULTS)

    try:
        response = _tavily_post(
            "search",
            {
                "query": query,
                "max_results": max_results,
                "include_raw_content": False,
                "include_images": False,
            },
        )
    except ValueError as exc:
        return _error(str(exc))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return _error(f"Tavily search failed: HTTP {exc.code}: {detail or exc.reason}")
    except URLError as exc:
        reason = getattr(exc, "reason", None) or str(exc)
        return _error(f"Tavily search failed: {reason}")
    except TimeoutError:
        return _error("Tavily search timed out")
    except Exception as exc:
        return _error(f"Tavily search failed: {type(exc).__name__}: {exc}")

    results = []
    for index, item in enumerate(response.get("results", []), start=1):
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "title": item.get("title", "") or "",
                "url": item.get("url", "") or "",
                "description": item.get("content", "") or "",
                "position": index,
            }
        )

    return json.dumps({"success": True, "results": results}, ensure_ascii=False)


def web_extract(args: dict) -> str:
    urls = args.get("urls")
    if not isinstance(urls, list) or not urls:
        return _error("urls must be a non-empty list")
    if len(urls) > _MAX_EXTRACT_URLS:
        return _error(f"web_extract accepts at most {_MAX_EXTRACT_URLS} URLs per call")

    normalized_urls: List[str] = []
    for raw_url in urls:
        if not isinstance(raw_url, str):
            return _error("Each URL must be a string")
        url = raw_url.strip()
        problem = _validate_http_url(url)
        if problem:
            return _error(f"Invalid URL '{raw_url}': {problem}")
        normalized_urls.append(url)

    format_name = (args.get("format") or "markdown").strip().lower()
    if format_name not in {"markdown", "text"}:
        return _error("format must be 'markdown' or 'text'")

    extract_depth = (args.get("extract_depth") or "basic").strip().lower()
    if extract_depth not in {"basic", "advanced"}:
        return _error("extract_depth must be 'basic' or 'advanced'")

    try:
        response = _tavily_post(
            "extract",
            {
                "urls": normalized_urls,
                "extract_depth": extract_depth,
                "format": format_name,
                "include_images": False,
                "include_favicon": False,
            },
        )
    except ValueError as exc:
        return _error(str(exc))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return _error(f"Tavily extract failed: HTTP {exc.code}: {detail or exc.reason}")
    except URLError as exc:
        reason = getattr(exc, "reason", None) or str(exc)
        return _error(f"Tavily extract failed: {reason}")
    except TimeoutError:
        return _error("Tavily extract timed out")
    except Exception as exc:
        return _error(f"Tavily extract failed: {type(exc).__name__}: {exc}")

    results = []
    for item in response.get("results", []):
        if not isinstance(item, dict):
            continue
        content = item.get("raw_content") or item.get("content") or ""
        content, truncated = _truncate_content(content)
        results.append(
            {
                "url": item.get("url", "") or "",
                "title": item.get("title", "") or "",
                "content": content,
                "truncated": truncated,
                "error": None,
            }
        )

    for item in response.get("failed_results", []):
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "url": item.get("url", "") or "",
                "title": item.get("title", "") or "",
                "content": "",
                "truncated": False,
                "error": item.get("error", "extraction failed") or "extraction failed",
            }
        )

    return json.dumps({"success": True, "results": results}, ensure_ascii=False)


WEB_SEARCH_SCHEMA = {
    "name": "web_search",
    "description": "Search the web for current information. Returns result metadata only: title, URL, description, and position.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query to look up on the web",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (1-5, default 5)",
                "minimum": 1,
                "maximum": 5,
            },
        },
        "required": ["query"],
    },
}

WEB_EXTRACT_SCHEMA = {
    "name": "web_extract",
    "description": "Extract page content from one or more web URLs. Returns up to 8000 characters of content per URL and marks truncated pages.",
    "parameters": {
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "description": "List of http/https URLs to extract (max 5 URLs per call)",
                "items": {"type": "string"},
                "maxItems": 5,
            },
            "format": {
                "type": "string",
                "description": "Extraction format. Use markdown by default, or text for plain text output.",
                "enum": ["markdown", "text"],
            },
            "extract_depth": {
                "type": "string",
                "description": "basic is faster/cheaper; advanced is heavier extraction for harder pages.",
                "enum": ["basic", "advanced"],
            },
        },
        "required": ["urls"],
    },
}


registry.register(
    name="web_search",
    toolset="web",
    schema=WEB_SEARCH_SCHEMA,
    handler=web_search,
    check_fn=_has_tavily_api_key,
)

registry.register(
    name="web_extract",
    toolset="web",
    schema=WEB_EXTRACT_SCHEMA,
    handler=web_extract,
    check_fn=_has_tavily_api_key,
)
