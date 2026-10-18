"""Fixed arithmetic and real LiteLLM utilities; network access is forbidden."""

from decimal import Decimal
import json
import os
import socket
import subprocess
import sys

import pytest

from astra_claw.cost import _calculator, estimate_cost
from astra_claw.usage_ledger import request_scope


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Cost calculation must not access the network")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)


def usage(cached=0):
    return {"prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200,
            "prompt_tokens_details": {"cached_tokens": cached},
            "completion_tokens_details": {"reasoning_tokens": 50}}


@pytest.mark.parametrize("provider,model,key", [
    ("openai", "gpt-4o-mini", "gpt-4o-mini"),
    ("openrouter", "openai/gpt-4o-mini", "openrouter/openai/gpt-4o-mini"),
])
@pytest.mark.parametrize("cached,expected", [(0, "0.00027"), (400, "0.00024")])
def test_real_catalog_and_cache_arithmetic(provider, model, key, cached, expected):
    result = estimate_cost(provider, model, usage(cached))
    assert result["cost_status"] == "estimated"
    assert result["estimated_cost_usd"] == pytest.approx(float(Decimal(expected)))
    assert result["cost_reason"] is None
    assert result["pricing"]["model"] == key
    assert result["pricing"]["library_version"] == "1.106.0"
    assert len(result["pricing"]["catalog_sha256"]) == 64
    assert result["pricing"]["effective_rates"]["input_cost_per_token"] == 1.5e-7
    # Reasoning is already part of completion_tokens: adding it again is wrong.
    assert result["cost_scope"] == "model_tokens"


@pytest.mark.parametrize("raw,reason", [
    (None, "missing_usage"),
    ({"prompt_tokens": 1}, "missing_usage"),
    ({"prompt_tokens": -1, "completion_tokens": 1}, "invalid_usage"),
    ({"prompt_tokens": True, "completion_tokens": 1}, "invalid_usage"),
    ({"prompt_tokens": 1000, "completion_tokens": 200}, "missing_cache_usage"),
])
def test_unknown_usage_is_not_free(raw, reason):
    result = estimate_cost("openai", "gpt-4o-mini", raw)
    assert result["estimated_cost_usd"] is None
    assert result["cost_status"] == "unknown" and result["cost_reason"] == reason


@pytest.mark.parametrize("provider,model,reason", [
    ("openai", "made-up-model-unknown", "unknown_model"),
    ("openrouter", "gpt-4o-mini", "unknown_model"),
    ("other-provider", "gpt-4o-mini", "unsupported_provider"),
])
def test_no_fuzzy_or_cross_provider_fallback(provider, model, reason):
    result = estimate_cost(provider, model, usage())
    assert result["estimated_cost_usd"] is None and result["cost_reason"] == reason


def test_unknown_resolved_model_does_not_use_requested_price():
    result = estimate_cost("openai", "gpt-4o-mini", usage(), response_model="unknown-resolved")
    assert result["cost_reason"] == "unknown_model"


@pytest.mark.parametrize("field,value", [("cached_tokens", 1001), ("cached_tokens", -1),
                                          ("audio_tokens", 40), ("cache_write_tokens", 10)])
def test_bad_cache_counts_and_unhandled_billing_are_unknown(field, value):
    raw = usage()
    raw["prompt_tokens_details"][field] = value
    result = estimate_cost("openai", "gpt-4o-mini", raw)
    assert result["estimated_cost_usd"] is None


def test_inconsistent_totals_are_unknown():
    raw = usage()
    raw["total_tokens"] = 2000
    assert estimate_cost("openai", "gpt-4o-mini", raw)["cost_reason"] == "invalid_usage"


def test_zero_usage_is_a_real_zero():
    result = estimate_cost("openai", "gpt-4o-mini", {"prompt_tokens": 0, "completion_tokens": 0})
    assert result["cost_status"] == "estimated" and result["estimated_cost_usd"] == 0


def test_priority_rate_and_missing_tier_prices():
    result = estimate_cost("openai", "gpt-4o-mini", usage(400), service_tier="priority")
    assert result["estimated_cost_usd"] == pytest.approx(0.0004)
    assert result["pricing"]["service_tier_source"] == "response"
    assert estimate_cost("openai", "gpt-4o-mini", usage(), service_tier="flex")["cost_reason"] == "missing_pricing"
    assert estimate_cost("openai", "gpt-4o-mini", usage(), service_tier="batch")["cost_reason"] == "unsupported_service_tier"


def test_missing_prices_and_complex_pricing_are_not_defaulted(monkeypatch):
    _, catalog, _, _ = _calculator()
    monkeypatch.delitem(catalog["gpt-4o-mini"], "cache_read_input_token_cost")
    assert estimate_cost("openai", "gpt-4o-mini", usage(400))["cost_reason"] == "missing_cache_pricing"
    monkeypatch.delitem(catalog["gpt-4o-mini"], "input_cost_per_token")
    assert estimate_cost("openai", "gpt-4o-mini", usage())["cost_reason"] == "missing_pricing"
    monkeypatch.setitem(catalog["gpt-4o-mini"], "input_cost_per_token_above_128k_tokens", 1e-6)
    assert estimate_cost("openai", "gpt-4o-mini", usage())["cost_reason"] == "unsupported_context_pricing"


def test_ledger_contains_one_estimate_per_request():
    from astra_claw.constants import get_astraclaw_home
    with request_scope("openai", "gpt-4o-mini", purpose="conversation") as evidence:
        evidence.raw_usage = usage(400)
    rows = [json.loads(line) for path in (get_astraclaw_home() / "usage").glob("*.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines()]
    finished = [row for row in rows if row["event"] == "request_finished"]
    assert len(finished) == 1
    assert finished[0]["estimated_cost_usd"] == pytest.approx(0.00024)
    assert finished[0]["raw_usage"] == usage(400)
    assert all("estimated_cost_usd" not in row for row in rows if row["event"] != "request_finished")


def test_incomplete_requests_do_not_claim_complete_cost():
    result = estimate_cost("openai", "gpt-4o-mini", usage(), request_status="interrupted")
    assert result["estimated_cost_usd"] is None
    assert result["cost_reason"] == "incomplete_request"


def test_calculation_failure_is_explicit(monkeypatch):
    library, _, _, _ = _calculator()

    def fail(**kwargs):
        raise ValueError("Cannot calculate this request")

    monkeypatch.setattr(library, "cost_per_token", fail)
    result = estimate_cost("openai", "gpt-4o-mini", usage())
    assert result["cost_status"] == "unknown"
    assert result["cost_reason"] == "calculation_error"


def test_returned_snapshot_cannot_mutate_catalog():
    result = estimate_cost("openai", "gpt-4o-mini", usage())
    result["pricing"]["entry"]["input_cost_per_token"] = 999
    assert estimate_cost("openai", "gpt-4o-mini", usage())["estimated_cost_usd"] == pytest.approx(0.00027)


def gpt55_usage(prompt, output=1000, cached=0):
    return {"prompt_tokens": prompt, "completion_tokens": output,
            "total_tokens": prompt + output,
            "prompt_tokens_details": {"cached_tokens": cached}}


@pytest.mark.parametrize("prompt,cached,expected,band", [
    (271999, 0, "1.389995", "short"),
    (272000, 0, "1.39", "short"),
    (272001, 0, "2.76501", "long"),
    (271999, 100000, "0.939995", "short"),
    (272000, 100000, "0.94", "short"),
    (272001, 100000, "1.86501", "long"),
    (272001, 272001, "0.317001", "long"),
])
@pytest.mark.parametrize("model", ["gpt-5.5", "gpt-5.5-2026-04-23"])
def test_gpt55_exact_threshold_and_whole_request_rates(prompt, cached, expected, band, model):
    result = estimate_cost("openai", model, gpt55_usage(prompt, cached=cached))
    assert result["cost_status"] == "estimated"
    assert result["estimated_cost_usd"] == pytest.approx(float(Decimal(expected)), abs=1e-12)
    pricing = result["pricing"]
    assert pricing["context_band"] == band
    assert pricing["context_threshold_tokens"] == 272000
    assert pricing["context_basis"] == "prompt_tokens_including_cache"
    # The base input rate still applies when only input + output crosses 272K.
    expected_key = "input_cost_per_token" + ("_above_272k_tokens" if band == "long" else "")
    assert pricing["rate_keys"]["input_cost_per_token"] == expected_key


def test_gpt55_service_tiers_do_not_fall_back_to_standard():
    short = estimate_cost("openai", "gpt-5.5", gpt55_usage(272000, cached=100000), service_tier="priority")
    assert short["estimated_cost_usd"] == pytest.approx(2.35)
    long = estimate_cost("openai", "gpt-5.5", gpt55_usage(272001, cached=100000), service_tier="flex")
    assert long["estimated_cost_usd"] == pytest.approx(0.932505)
    assert long["pricing"]["rate_keys"]["input_cost_per_token"] == "input_cost_per_token_above_272k_tokens_flex"
    # The bundled catalog has no priority long-context rates. Do not reuse short
    # priority or standard long-context rates to fill that gap.
    missing = estimate_cost("openai", "gpt-5.5", gpt55_usage(272001), service_tier="priority")
    assert missing["cost_reason"] == "missing_pricing" and missing["estimated_cost_usd"] is None


def test_gpt55_openrouter_uses_its_own_threshold_entry():
    result = estimate_cost("openrouter", "openai/gpt-5.5", gpt55_usage(272001, cached=100000))
    assert result["estimated_cost_usd"] == pytest.approx(1.86501)
    assert result["pricing"]["model"] == "openrouter/openai/gpt-5.5"


def test_gpt55_missing_long_cache_rate_stays_unknown(monkeypatch):
    _, catalog, _, _ = _calculator()
    monkeypatch.delitem(catalog["gpt-5.5"], "cache_read_input_token_cost_above_272k_tokens")
    result = estimate_cost("openai", "gpt-5.5", gpt55_usage(272001, cached=100000))
    assert result["cost_reason"] == "missing_cache_pricing"


def test_gpt55_unverified_threshold_remains_unknown(monkeypatch):
    _, catalog, _, _ = _calculator()
    monkeypatch.setitem(catalog["gpt-5.5"], "input_cost_per_token_above_128k_tokens", 1e-5)
    assert estimate_cost("openai", "gpt-5.5", gpt55_usage(1000))["cost_reason"] == "unsupported_context_pricing"


def test_saved_live_usage_samples_without_new_provider_call():
    # Counts from the authorized v0.4.2 live pilot. Keep this offline and do not
    # depend on a developer's home directory or rewrite the historical ledger.
    total = 0
    for prompt, output, reasoning, expected in ((805, 18, 0, 0.004565),
                                                (925, 153, 22, 0.009215),
                                                (1220, 51, 0, 0.00763)):
        raw = gpt55_usage(prompt, output)
        raw["completion_tokens_details"] = {"reasoning_tokens": reasoning}
        result = estimate_cost("openai", "gpt-5.5", raw,
                               response_model="gpt-5.5-2026-04-23", service_tier="default")
        assert result["estimated_cost_usd"] == pytest.approx(expected)
        total += result["estimated_cost_usd"]
    assert total == pytest.approx(0.02141)


def test_first_import_and_estimate_work_without_network():
    # A separate interpreter proves the initial LiteLLM import is offline too.
    script = """
import socket
def blocked(*args, **kwargs):
    raise AssertionError('network access attempted')
socket.socket.connect = blocked
socket.socket.connect_ex = blocked
from astra_claw.cost import estimate_cost
r = estimate_cost('openai', 'gpt-4o-mini', {
    'prompt_tokens': 1000, 'completion_tokens': 200,
    'prompt_tokens_details': {'cached_tokens': 400}})
assert r['cost_status'] == 'estimated', r
print(r['estimated_cost_usd'])
"""
    env = {**os.environ, "LITELLM_LOCAL_MODEL_COST_MAP": "False"}
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True,
                            text=True, timeout=45, check=True)
    assert float(result.stdout.strip()) == pytest.approx(0.00024)
