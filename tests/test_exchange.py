"""Tests for Sniper V2 live exchange rate fetcher."""
from __future__ import annotations

import sniper_v2.exchange as exchange_module
import pytest
from sniper_v2.exchange import (
    _DEFAULTS,
    _cache_get,
    _cache_set,
    _extract_rate,
    _normalize_pair,
    get_exchange_rates,
    fetch_rate,
)


@pytest.fixture(autouse=True)
def _clear_exchange_cache():
    exchange_module._cache.clear()
    yield
    exchange_module._cache.clear()


def test_normalize_pair_uppercases_and_joins():
    assert _normalize_pair("usd", "krw") == "USD_KRW"
    assert _normalize_pair("UsD", "KrW") == "USD_KRW"
    assert _normalize_pair("jpy", "krw") == "JPY_KRW"


def test_extract_rate_from_formatted_answer():
    text = "Current rate: 1 USD = 1352.5 KRW as of now."
    assert _extract_rate(text, "USD", "KRW") == 1352.5


def test_extract_rate_from_plain_number():
    text = "The rate is 9.21 JPY per KRW pair."
    assert _extract_rate(text, "KRW", "JPY") == 9.21


def test_extract_rate_returns_none_for_unparseable_text():
    assert _extract_rate("no numbers here", "USD", "KRW") is None


def test_fetch_rate_uses_default_when_llm_unavailable(monkeypatch):
    monkeypatch.setattr("sniper_v2.exchange._fetch_rate_via_llm", lambda *args, **kwargs: None)
    rate = fetch_rate("USD", "KRW")
    assert rate == 1350.0


def test_fetch_rate_caches_between_calls(monkeypatch):
    calls = []

    def fake_fetch(base, quote):
        calls.append((base, quote))
        return 1377.7

    monkeypatch.setattr("sniper_v2.exchange._fetch_rate_via_llm", fake_fetch)
    first = fetch_rate("USD", "KRW", ttl=60)
    second = fetch_rate("USD", "KRW", ttl=60)
    assert first == 1377.7
    assert second == 1377.7
    assert len(calls) == 1


def test_fetch_rate_raises_when_no_rate_available(monkeypatch):
    monkeypatch.setattr("sniper_v2.exchange._fetch_rate_via_llm", lambda *args, **kwargs: None)
    monkeypatch.setitem(_DEFAULTS, "FOO_KRW", 0.0)
    try:
        fetch_rate("FOO", "KRW")
    except RuntimeError as exc:
        assert "FOO->KRW" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_get_exchange_rates_returns_quoted_currency_as_one():
    rates = get_exchange_rates(["KRW"], quote="KRW")
    assert rates["KRW"] == 1.0
