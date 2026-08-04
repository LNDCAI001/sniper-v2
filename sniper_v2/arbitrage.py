"""Arbitrage calculations for Sniper V2.

Compares Korean used-market prices to baselines from Danawa and
configurable foreign-market reference prices.

Outputs margin estimates and flags opportunities.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ArbitrageOpportunity:
    listing: dict[str, Any]
    baseline_krw: int
    baseline_region: str
    baseline_source: str
    margin_krw: int
    margin_pct: float
    signal: str  # steal | alert | normal

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.listing.get("title") or self.listing.get("name") or "",
            "price_krw": self.listing.get("price") or self.listing.get("price_krw") or 0,
            "platform": self.listing.get("platform", ""),
            "url": self.listing.get("url", ""),
            "baseline_krw": self.baseline_krw,
            "baseline_region": self.baseline_region,
            "baseline_source": self.baseline_source,
            "margin_krw": self.margin_krw,
            "margin_pct": round(self.margin_pct, 1),
            "signal": self.signal,
        }


@dataclass
class PriceBaseline:
    model_key: str
    region: str
    price: int = 0
    currency: str = "KRW"
    source: str = ""
    url: str = ""
    fetched_at: str = ""

    @property
    def price_krw(self) -> int:
        if self.currency.upper() == "KRW":
            return self.price
        rate = _DEFAULT_RATES.get(self.currency.upper(), 1.0)
        if rate <= 0:
            return self.price
        return int(self.price * rate)


_DEFAULT_RATES = {
    "KRW": 1.0,
    "USD": 1350.0,
    "JPY": 9.2,
    "EUR": 1450.0,
}


def _extract_price(listing: dict[str, Any]) -> int:
    for key in ("price", "price_krw", "price_text"):
        raw = listing.get(key)
        if raw is None:
            continue
        text = str(raw)
        digits = "".join(ch for ch in text if ch.isdigit())
        if digits:
            try:
                return int(digits)
            except ValueError:
                continue
    return 0


def _to_krw(price: int, currency: str, exchange_rates: dict[str, float]) -> int:
    rate = exchange_rates.get(currency.upper(), 1.0)
    if rate <= 0:
        return price
    return int(price * rate)


def _normalize(text: str) -> str:
    text = text.lower()
    # map common Korean/English model aliases to normalized tokens
    aliases = {
        "맥북프로": "macbook pro",
        "맥북": "macbook",
        "맥스튜디오": "mac studio",
        "스트릭스할로": "strix halo",
        "스트릭스 할로": "strix halo",
        "m4 맥스": "m4 max",
        "m4 pro": "m4 pro",
        "m4": "m4",
        "m3": "m3",
        "m2": "m2",
        "울트라": "ultra",
        "프로": "pro",
        "맥스": "max",
        "미니": "mini",
        "핸드헬드": "handheld",
        "노트북": "laptop",
    }
    for k, v in aliases.items():
        text = text.replace(k, v)
    # strip parenthetical specs, SKUs, punctuation
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = [tok for tok in text.split() if len(tok) > 1]
    return " ".join(tokens)


def _match_model(listing: dict[str, Any], model_key: str) -> bool:
    haystack = _normalize((listing.get("title") or listing.get("name") or "") + " " + (listing.get("name") or ""))
    model = _normalize(model_key)
    if not model:
        return False
    model_tokens = [tok for tok in model.split() if len(tok) > 1]
    if not model_tokens:
        return False
    # Require all significant model tokens to be present in listing text
    return all(tok in haystack for tok in model_tokens)


def _margin_signal(margin_pct: float, thresholds: dict[str, float]) -> str:
    steal = thresholds.get("steal", 15.0)
    alert = thresholds.get("alert", 5.0)
    if margin_pct >= steal:
        return "steal"
    if margin_pct >= alert:
        return "alert"
    return "normal"


def evaluate_arbitrage(
    listings: list[dict[str, Any]],
    baselines: list[PriceBaseline],
    exchange_rates: dict[str, float] | None = None,
    thresholds: dict[str, float] | None = None,
) -> list[ArbitrageOpportunity]:
    """Compare listings to price baselines and return margin opportunities."""
    if exchange_rates is None:
        exchange_rates = {"KRW": 1.0, "USD": 1350.0, "JPY": 9.2}
    if thresholds is None:
        thresholds = {"steal": 15.0, "alert": 5.0}

    opportunities: list[ArbitrageOpportunity] = []
    for listing in listings:
        price = _extract_price(listing)
        if price <= 0:
            continue
        for baseline in baselines:
            if not _match_model(listing, baseline.model_key):
                continue
            baseline_krw = baseline.price_krw if baseline.currency.upper() == "KRW" else _to_krw(
                baseline.price_krw, baseline.currency, exchange_rates
            )
            if baseline_krw <= 0:
                continue
            margin_krw = baseline_krw - price
            margin_pct = (margin_krw / baseline_krw) * 100.0
            signal = _margin_signal(margin_pct, thresholds)
            opp = ArbitrageOpportunity(
                listing=listing,
                baseline_krw=baseline_krw,
                baseline_region=baseline.region,
                baseline_source=baseline.source,
                margin_krw=margin_krw,
                margin_pct=margin_pct,
                signal=signal,
            )
            opportunities.append(opp)
    opportunities.sort(key=lambda x: x.margin_pct, reverse=True)
    return opportunities


def build_baselines_from_danawa(
    danawa_listings: list[dict[str, Any]],
    region: str = "KR",
    source: str = "danawa",
) -> list[PriceBaseline]:
    """Build price baselines from Danawa listings, keyed by product name."""
    baselines: list[PriceBaseline] = []
    for item in danawa_listings:
        name = item.get("name") or item.get("title") or ""
        price = item.get("price_krw") or item.get("price") or 0
        if not name or price <= 0:
            continue
        baselines.append(
            PriceBaseline(
                model_key=name.strip(),
                region=region,
                price=price,
                source=source,
                url=item.get("url", ""),
            )
        )
    return baselines


def build_baselines_from_foreign_markets(
    foreign_markets: list[dict[str, Any]],
    exchange_rates: dict[str, float] | None = None,
) -> list[PriceBaseline]:
    """Build price baselines from configurable foreign-market entries."""
    if exchange_rates is None:
        exchange_rates = {"KRW": 1.0, "USD": 1350.0, "JPY": 9.2, "EUR": 1450.0}
    baselines: list[PriceBaseline] = []
    for market in foreign_markets:
        model_key = market.get("model_key") or market.get("model") or ""
        price = market.get("price") or market.get("price_krw") or 0
        currency = (market.get("currency") or "KRW").upper()
        region = market.get("region") or currency
        source = market.get("source") or "foreign"
        url = market.get("url") or ""
        if not model_key or price <= 0:
            continue
        price_krw = price if currency == "KRW" else _to_krw(price, currency, exchange_rates)
        baselines.append(
            PriceBaseline(
                model_key=model_key.strip(),
                region=region,
                price=price_krw,
                currency="KRW",
                source=source,
                url=url,
            )
        )
    return baselines
