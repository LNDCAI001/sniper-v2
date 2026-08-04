"""Deterministic verification gate (Ralph-style).

Runs only structural and rule-based checks on a scraped listing.
NO LLM trust — every check is a hard Python assertion.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Domains known to serve stock photography
_STOCK_DOMAIN_RE = re.compile(
    r"(apple\.com|msi\.com|lg\.com|samsung\.com|amazon\.com|"
    r"prod\.danawa\.com|cdn\.shopify\.com|shopify\.com|gmktec\.com|"
    r"beelink\.com|minisforum\.com|ayaneo\.com|gpd\.hk|onexfly\.com)",
    re.IGNORECASE,
)

# Path/URL patterns that indicate a stock photo
_STOCK_PATH_RE = re.compile(
    r"product[-_]?image|official[-_]?photo|press[-_]?kit|render[-_]?final",
    re.IGNORECASE,
)


@dataclass
class VerificationResult:
    passed: bool = True
    reasons: list[str] = field(default_factory=list)

    def fail(self, reason: str) -> None:
        self.passed = False
        self.reasons.append(reason)
        logger.warning("VERIFY FAIL: %s", reason)

    def __bool__(self) -> bool:
        return self.passed


def verify_listing(
    listing: dict[str, Any],
    anti_fraud: dict[str, Any] | None = None,
    price_thresholds: dict[str, int] | None = None,
    platform: str = "",
) -> VerificationResult:
    """Run all deterministic checks on a listing dict.

    Parameters
    ----------
    listing:
        Scraped listing data.  Must contain at least *url* and either
        *title* or *name*.
    anti_fraud:
        Anti-fraud config dict.  Falls back to defaults if omitted.
    price_thresholds:
        Price threshold dict.  Falls back to defaults if omitted.

    Returns
    -------
    VerificationResult
        ``.passed`` is ``True`` when every check succeeds.
    """
    result = VerificationResult()
    af = anti_fraud or {}
    thresholds = price_thresholds or {}

    # --- required fields --------------------------------------------------
    url = listing.get("url", "")
    title = listing.get("title") or listing.get("name") or ""
    if not url:
        result.fail("missing url")
    if not title:
        result.fail("missing title/name")

    # --- not a registration / generic page --------------------------------
    if _is_registration_page(url, title):
        result.fail("listing looks like a registration or generic page")

    # --- numeric price check ----------------------------------------------
    price = _extract_price(listing)
    if price is None:
        result.fail("no numeric price found")
    else:
        min_price = thresholds.get("suspicious_min", 500_000)
        if 0 < price < min_price:
            result.fail(f"price {price:,} below suspicious minimum {min_price:,}")

    # --- stock photo check ------------------------------------------------
    image = listing.get("image", "") or listing.get("image_url", "") or ""
    if image:
        if _is_stock_photo(image, title):
            result.fail("image or title indicates stock photo")

    # --- domain check -----------------------------------------------------
    if url:
        host = url.split("/")[2].lower() if "://" in url else url.lower()
        if host != "prod.danawa.com" and _STOCK_DOMAIN_RE.search(url):
            result.fail("URL points to known stock-photo domain")

    return result


def _extract_price(listing: dict[str, Any]) -> int | None:
    """Pull the first numeric price from known fields."""
    for key in ("price", "price_krw", "price_text"):
        raw = listing.get(key)
        if raw is None:
            continue
        text = str(raw)
        m = re.search(r"[\d,]+", text)
        if m:
            try:
                return int(m.group(0).replace(",", ""))
            except ValueError:
                continue
    return None


def _is_registration_page(url: str, title: str) -> bool:
    url_lower = url.lower()
    title_lower = title.lower()
    registration_hints = [
        "signup", "register", "login", "회원가입", "로그인",
    ]
    if any(h in url_lower for h in registration_hints):
        return True
    if not title:
        return False
    if any(h in title_lower for h in registration_hints):
        return True
    return False


def _is_stock_photo(image_url: str, title: str) -> bool:
    if _STOCK_PATH_RE.search(image_url):
        return True
    if _STOCK_PATH_RE.search(title):
        return True
    # Check known stock domains in image URL
    if _STOCK_DOMAIN_RE.search(image_url):
        return True
    return False


def verify_listing_daangn(listing: dict[str, Any], cfg: Any) -> VerificationResult:
    return verify_listing(listing, cfg.anti_fraud.dict(), cfg.price_thresholds.dict())


def verify_listing_joongna(listing: dict[str, Any], cfg: Any) -> VerificationResult:
    return verify_listing(listing, cfg.anti_fraud.dict(), cfg.price_thresholds.dict())
