"""Live exchange rate fetcher for Sniper V2 arbitrage.

Fetches KRW-based rates via Perplexity with Exa fallback and
in-memory caching.  All rates are expressed as ``foreign -> KRW``
multipliers, e.g. ``USD=1350.0`` means 1 USD = 1350 KRW.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional sovereign-testbench import
# ---------------------------------------------------------------------------
_SB_PATH = "C:/Users/Dachi/sovereign-testbench/src"
if _SB_PATH not in sys.path:
    sys.path.insert(0, _SB_PATH)

try:
    from sovereign_testbench.perplexity_ask import ask as perplexity_ask  # type: ignore[import]
except Exception:  # pragma: no cover
    perplexity_ask = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
_CACHE_TTL_S = 1800
_cache: dict[str, tuple[float, float]] = {}  # pair -> (value, expiry_ts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _cache_get(pair: str) -> float | None:
    entry = _cache.get(pair)
    if not entry:
        return None
    value, expiry = entry
    if time.time() >= expiry:
        _cache.pop(pair, None)
        return None
    return value


def _cache_set(pair: str, value: float, ttl: float = _CACHE_TTL_S) -> None:
    _cache[pair] = (value, time.time() + ttl)


def _normalize_pair(base: str, quote: str) -> str:
    return f"{base.upper()}_{quote.upper()}"


def _extract_rate(text: str, base: str, quote: str) -> float | None:
    """Best-effort numeric extraction from an LLM/search answer."""
    import re
    base_u = base.upper()
    quote_u = quote.upper()
    patterns = [
        rf"{base_u}[/=:]\s*([0-9]+(?:\.[0-9]+)?)\s*{quote_u}",
        rf"1\s*{base_u}\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*{quote_u}",
        rf"{quote_u}\s*([0-9]+(?:\.[0-9]+)?)\s*per\s*{base_u}",
        rf"([0-9]+(?:\.[0-9]+))\s*{quote_u}",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    nums = re.findall(r"[0-9]+(?:\.[0-9]+)", text)
    if nums:
        try:
            return float(nums[0])
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------
def _ask_perplexity(prompt: str) -> str:
    if perplexity_ask is None:
        return ""
    try:
        return perplexity_ask("perplexity/best", prompt, search=True)
    except Exception as exc:  # pragma: no cover
        logger.debug("Perplexity rate fetch failed: %s", exc)
        return ""


def _ask_exa(prompt: str) -> str:
    api_key = os.getenv("EXA_API_KEY") or os.getenv("SNIPER_EXA_API_KEY", "")
    if not api_key:
        return ""
    try:
        import requests  # type: ignore[import-untyped]

        resp = requests.post(
            "https://api.exa.ai/search",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"query": prompt, "num_results": 3},
            timeout=20,
        )
        if resp.status_code != 200:
            return ""
        data = resp.json()
        text = data.get("answer") or ""
        if not text:
            results = data.get("results") or []
            text = " ".join(item.get("text", "") for item in results[:3])
        return text
    except Exception as exc:  # pragma: no cover
        logger.debug("Exa rate fetch failed: %s", exc)
        return ""


def _fetch_rate_via_llm(base: str, quote: str) -> float | None:
    prompt = (
        f"What is the current exchange rate from {base} to {quote}? "
        f"Answer with only the numeric rate, e.g. 1 {base} = X {quote}."
    )
    text = _ask_perplexity(prompt)
    if not text:
        text = _ask_exa(prompt)
    if not text:
        return None
    return _extract_rate(text, base, quote)


def fetch_rate(base: str, quote: str = "KRW", ttl: float = _CACHE_TTL_S) -> float:
    """Return ``1 base = ? quote`` with live lookup and fallback."""
    pair = _normalize_pair(base, quote)
    cached = _cache_get(pair)
    if cached is not None:
        return cached

    value = _fetch_rate_via_llm(base, quote)
    if value is None or value <= 0:
        value = _DEFAULTS.get(pair)
    if value is None or value <= 0:
        raise RuntimeError(f"unable to fetch exchange rate {base}->{quote}")
    _cache_set(pair, value, ttl=ttl)
    return value


def get_exchange_rates(
    bases: list[str] | None = None,
    quote: str = "KRW",
) -> dict[str, float]:
    """Return rates for multiple bases, e.g. ``{"USD": 1350.0, "JPY": 9.2}``."""
    if bases is None:
        bases = ["USD", "JPY", "EUR", "KRW"]
    out: dict[str, float] = {}
    for base in bases:
        base = base.upper()
        if base == quote.upper():
            out[base] = 1.0
            continue
        out[base] = fetch_rate(base, quote)
    return out


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
_DEFAULTS: dict[str, float] = {
    "USD_KRW": 1350.0,
    "JPY_KRW": 9.2,
    "EUR_KRW": 1450.0,
    "KRW_KRW": 1.0,
}
