"""Offline token-cost estimates using a pinned LiteLLM price catalog.

This does not call models or route requests. Unknown cost is never zero.
"""

from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
from importlib.metadata import version
from importlib.resources import files
import json
import math
import os


@lru_cache(maxsize=1)
def _calculator():
    # LiteLLM otherwise downloads its price map during import. Read the bundled
    # file ourselves too: external mutations of litellm.model_cost cannot change
    # the prices used by Astra's calculator.
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    import litellm

    litellm.telemetry = False
    body = files("litellm").joinpath("model_prices_and_context_window_backup.json").read_bytes()
    return litellm, json.loads(body), version("litellm"), sha256(body).hexdigest()


def _count(value):
    return type(value) is int and value >= 0


def _rate(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def estimate_cost(provider, model, raw_usage, *, response_model=None, service_tier=None,
                  request_status="completed"):
    """Return a token estimate plus its pricing evidence, or an explicit unknown.

    Only OpenAI-compatible token usage for Astra's OpenAI/OpenRouter routes is
    supported. GPT-5.5's verified 272K context tiers are supported; other context
    rules, cache writes, and media-specific rates remain unknown.
    """
    result = {
        "estimated_cost_usd": None,
        "cost_status": "unknown",
        "cost_reason": None,
        "cost_currency": "USD",
        "cost_scope": "model_tokens",
        "pricing": None,
    }

    def unknown(reason):
        return {**result, "cost_reason": reason}

    if request_status != "completed":
        return unknown("incomplete_request")
    if not isinstance(raw_usage, dict):
        return unknown("missing_usage")
    prompt = raw_usage.get("prompt_tokens")
    output = raw_usage.get("completion_tokens")
    if prompt is None or output is None:
        return unknown("missing_usage")
    if not _count(prompt) or not _count(output):
        return unknown("invalid_usage")
    total = raw_usage.get("total_tokens")
    if total is not None and (not _count(total) or total != prompt + output):
        return unknown("invalid_usage")
    if provider not in {"openai", "openrouter"}:
        return unknown("unsupported_provider")

    library, catalog, library_version, catalog_hash = _calculator()
    resolved = response_model or model
    prefix = f"{provider}/"
    key = resolved if resolved.startswith(prefix) else prefix + resolved
    # OpenAI's bundled entries generally use bare model names. Never fall back
    # from OpenRouter to OpenAI pricing, or guess an unknown model by similarity.
    if provider == "openai" and key not in catalog:
        key = key[len(prefix):]
    entry = catalog.get(key)
    if not isinstance(entry, dict) or entry.get("litellm_provider") != provider:
        return unknown("unknown_model")
    tier = service_tier or "default"
    result["pricing"] = {
        "source": "litellm_bundled",
        "library_version": library_version,
        "catalog_sha256": catalog_hash,
        "model": key,
        "service_tier": tier,
        "service_tier_source": "response" if service_tier else "assumed_default",
        "entry": deepcopy(entry),
    }
    if tier not in {"default", "standard", "priority", "flex"}:
        return unknown("unsupported_service_tier")
    context_suffix = ""
    if any("above_" in name or name == "tiered_pricing" for name in entry):
        # Only this model family's 272K rule has been verified. Do not infer
        # other models' threshold semantics just from similarly named keys.
        verified_model = key in {
            "gpt-5.5", "gpt-5.5-2026-04-23", "openrouter/openai/gpt-5.5",
        }
        if (not verified_model or "tiered_pricing" in entry or any(
                "above_" in name and "_above_272k_tokens" not in name for name in entry)):
            return unknown("unsupported_context_pricing")
        # prompt_tokens already includes cache reads. The threshold is strict,
        # and selects rates for all tokens, not only tokens past the boundary.
        if prompt > 272000:
            context_suffix = "_above_272k_tokens"
        result["pricing"].update({
            "context_threshold_tokens": 272000,
            "context_band": "long" if context_suffix else "short",
            "context_basis": "prompt_tokens_including_cache",
        })

    prompt_details = raw_usage.get("prompt_tokens_details") or {}
    output_details = raw_usage.get("completion_tokens_details") or {}
    if not isinstance(prompt_details, dict) or not isinstance(output_details, dict):
        return unknown("invalid_usage")
    cached = prompt_details.get("cached_tokens")
    if cached is None:
        if prompt:
            return unknown("missing_cache_usage")
        cached = 0  # Zero total input proves there are no cache-read tokens.
    if not _count(cached) or cached > prompt:
        return unknown("invalid_usage")
    reasoning = output_details.get("reasoning_tokens")
    if reasoning is not None and (not _count(reasoning) or reasoning > output):
        return unknown("invalid_usage")
    for details in (prompt_details, output_details):
        for name in ("audio_tokens", "video_tokens", "image_tokens", "cache_write_tokens", "cache_creation_tokens"):
            value = details.get(name)
            if value is not None and (not _count(value) or value != 0):
                return unknown("unsupported_usage_details")
    for name in ("cache_read_input_tokens", "cache_creation_input_tokens"):
        value = raw_usage.get(name)
        if value is not None and (not _count(value) or value != 0):
            return unknown("unsupported_usage_details")

    suffix = f"_{tier}" if tier in {"priority", "flex"} else ""
    rate_keys = {name: name + context_suffix + suffix for name in (
        "input_cost_per_token", "output_cost_per_token", "cache_read_input_token_cost",
    )}
    result["pricing"]["rate_keys"] = rate_keys
    rates = {name: entry.get(source_key) for name, source_key in rate_keys.items()}
    if not all(_rate(rates[name]) for name in ("input_cost_per_token", "output_cost_per_token")):
        return unknown("missing_pricing")
    if cached and not _rate(rates["cache_read_input_token_cost"]):
        return unknown("missing_cache_pricing")
    if rates["cache_read_input_token_cost"] is None:
        del rates["cache_read_input_token_cost"]
    result["pricing"]["effective_rates"] = rates
    # Usage contains cache tokens as a subset of prompt tokens. Passing the
    # separate cache_read_input_tokens argument would imply Anthropic semantics.
    usage = library.Usage(prompt_tokens=prompt, completion_tokens=output,
                          total_tokens=prompt + output,
                          prompt_tokens_details={"cached_tokens": cached})
    try:
        input_cost, output_cost = library.cost_per_token(
            model=key, prompt_tokens=prompt, completion_tokens=output,
            usage_object=usage, custom_cost_per_token=rates,
        )
    except (ValueError, TypeError, KeyError, ArithmeticError):
        # Preserve request evidence even when the cost utility cannot price it.
        return unknown("calculation_error")
    cost = input_cost + output_cost
    if not _rate(cost):
        return unknown("invalid_calculation")
    return {**result, "estimated_cost_usd": cost, "cost_status": "estimated"}
