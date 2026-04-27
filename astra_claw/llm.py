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


def resolve_api_key(provider: str, model_config: Optional[Dict[str, Any]] = None) -> str:
    """Resolve the API key for a provider.

    Lookup order:
      1. ``model_config['api_key']`` (set by the setup wizard)
      2. The provider's environment variable

    Returns an empty string when no key is configured.
    """
    if model_config:
        configured = (model_config.get("api_key") or "").strip()
        if configured:
            return configured
    env_var = PROVIDER_KEY_ENV.get(provider, "OPENAI_API_KEY")
    return os.getenv(env_var, "") or ""


def create_client(provider: str, api_key: Optional[str] = None) -> OpenAI:
    """Create an OpenAI-compatible client for the requested provider.

    ``api_key`` wins over the environment variable when provided.
    """
    base_url = PROVIDER_BASE_URLS.get(provider, PROVIDER_BASE_URLS["openai"])
    key = (api_key or "").strip()
    if not key:
        env_var = PROVIDER_KEY_ENV.get(provider, "OPENAI_API_KEY")
        key = os.getenv(env_var, "")

    if not key:
        env_var = PROVIDER_KEY_ENV.get(provider, "OPENAI_API_KEY")
        raise RuntimeError(
            f"No API key found for {provider}. "
            f"Run 'astraclaw setup' or set {env_var}."
        )

    return OpenAI(base_url=base_url, api_key=key)


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
    api_key: Optional[str] = None,
) -> str:
    """Run a single non-streaming chat completion and return the text.

    Handles both the legacy `max_tokens` parameter and the newer
    `max_completion_tokens` required by reasoning / gpt-5.x models.
    """
    client = create_client(provider, api_key=api_key)
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


def validate_credentials(
    provider: str,
    api_key: str,
    *,
    timeout: float = 5.0,
) -> tuple[bool, str]:
    """Ping the provider's /models endpoint to verify the API key.

    Returns ``(ok, message)``. ``message`` describes the failure when ``ok`` is
    False, and is empty on success.
    """
    key = (api_key or "").strip()
    if not key:
        return False, "API key is empty."
    try:
        client = OpenAI(
            base_url=PROVIDER_BASE_URLS.get(provider, PROVIDER_BASE_URLS["openai"]),
            api_key=key,
            timeout=timeout,
        )
        client.models.list()
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        if status == 401 or status == 403:
            return False, "Provider rejected the API key (unauthorized)."
        if status == 404:
            return False, "Provider endpoint not found - check the base URL."
        text = str(exc).lower()
        if "timeout" in text or "timed out" in text:
            return False, f"Connection to {provider} timed out after {timeout:.0f}s."
        if "connection" in text:
            return False, f"Could not connect to {provider}."
        return False, f"Validation failed: {exc}"
    return True, ""


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
