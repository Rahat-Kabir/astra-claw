"""LLM provider helpers for Astra-Claw."""

import os
from typing import Any, Dict, Optional

from openai import OpenAI


PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def create_client(provider: str) -> OpenAI:
    """Create an OpenAI-compatible client for the requested provider."""
    base_url = PROVIDER_BASE_URLS.get(provider, PROVIDER_BASE_URLS["openai"])
    api_key_env = PROVIDER_KEY_ENV.get(provider, "OPENAI_API_KEY")
    api_key = os.getenv(api_key_env, "")

    if not api_key:
        raise RuntimeError(f"No API key found. Set {api_key_env} environment variable.")

    return OpenAI(base_url=base_url, api_key=api_key)


def build_route(model_config: Dict[str, Any], fallback: bool = False) -> Optional[Dict[str, str]]:
    """Resolve the provider/model pair for the primary or fallback route."""
    if fallback:
        provider = model_config.get("fallback_provider")
        if not provider:
            return None
        model = model_config.get("fallback_model") or model_config.get("default", "gpt-5.4-mini")
    else:
        provider = model_config.get("provider", "openai")
        model = model_config.get("default", "gpt-5.4-mini")

    return {"provider": provider, "model": model}


def complete_once(
    messages: list,
    *,
    provider: str,
    model: str,
    max_tokens: int = 30,
    temperature: float = 0.3,
    timeout: float = 30.0,
) -> str:
    """Run a single non-streaming chat completion and return the text.

    Handles both the legacy `max_tokens` parameter and the newer
    `max_completion_tokens` required by reasoning / gpt-5.x models.
    """
    client = create_client(provider)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_completion_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )
    except Exception as exc:
        if "max_completion_tokens" not in str(exc):
            raise
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )
    return (resp.choices[0].message.content or "").strip()


def is_failover_worthy_error(exc: Exception) -> bool:
    """Return True only for transient/runtime failures worth retrying on fallback."""
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return True
    if isinstance(status_code, int):
        if status_code >= 500:
            return True
        if status_code in {400, 401, 403, 404, 409, 422}:
            return False

    haystack = f"{exc.__class__.__name__} {exc}".lower()

    transient_markers = (
        "timeout",
        "timed out",
        "connection",
        "connect",
        "rate limit",
        "ratelimit",
        "server error",
        "service unavailable",
        "temporarily unavailable",
        "apiconnection",
        "apitimeout",
    )
    if any(marker in haystack for marker in transient_markers):
        return True

    permanent_markers = (
        "authentication",
        "unauthorized",
        "forbidden",
        "invalid api key",
        "bad request",
        "invalid request",
        "malformed",
        "schema",
        "tool schema",
    )
    if any(marker in haystack for marker in permanent_markers):
        return False

    return False
