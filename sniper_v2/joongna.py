"""Joongna (중고나라) scraper.

Primary path: Apify actor ``kdatafactory/joongna-scraper``.
Fallback: direct HTTP + BeautifulSoup against ``web.joongna.com``.

Extracts:
  listing_id, name, price_krw, status, wish_count, chat_count,
  image_url, listed_at, url
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


@dataclass
class JoongnaListing:
    listing_id: str = ""
    name: str = ""
    price_krw: int = 0
    price_text: str = ""
    status: str = "unknown"
    wish_count: int = 0
    chat_count: int = 0
    image_url: str = ""
    listed_at: str = ""
    url: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "listing_id": self.listing_id,
            "name": self.name,
            "price_krw": self.price_krw,
            "price_text": self.price_text,
            "status": self.status,
            "wish_count": self.wish_count,
            "chat_count": self.chat_count,
            "image_url": self.image_url,
            "listed_at": self.listed_at,
            "url": self.url,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_price(text: str) -> int:
    cleaned = text.replace(",", "").replace("원", "").replace("₩", "").strip()
    cleaned = re.sub(r"[^\d]", "", cleaned)
    return int(cleaned) if cleaned else 0


def _normalize_status(raw: str) -> str:
    s = raw.lower()
    if "판매" in raw or "sale" in s:
        return "for-sale"
    if "예약" in raw or "reserved" in s:
        return "reserved"
    if "완료" in raw or "sold" in s or "done" in s:
        return "sold"
    return raw or "unknown"


# ---------------------------------------------------------------------------
# Apify path
# ---------------------------------------------------------------------------

class ApifyJoongnaScraper:
    """Wrapper around the Apify ``kdatafactory/joongna-scraper`` actor."""

    def __init__(self, token: str | None = None) -> None:
        self.token = token or os.getenv("APIFY_TOKEN") or os.getenv("SNIPER_APIFY_TOKEN", "")
        self.base = "https://api.apify.com/v2"

    def search(self, query: str, max_items: int = 50) -> list[JoongnaListing]:
        if not self.token:
            raise RuntimeError("APIFY_TOKEN not configured — cannot use Apify actor")

        start_url = (
            f"{self.base}/acts/kdatafactory~joongna-scraper/runs"
            f"?token={self.token}"
        )
        payload = {
            "queries": [query],
            "maxItemsPerQuery": max_items,
            "proxy": {"useApifyProxy": True},
        }
        resp = requests.post(start_url, json=payload, timeout=60)
        resp.raise_for_status()
        run = resp.json().get("data", {}).get("id", "")

        for _ in range(30):
            status_url = f"{self.base}/actor-runs/{run}?token={self.token}"
            r = requests.get(status_url, timeout=20)
            r.raise_for_status()
            status = r.json().get("data", {}).get("status", "")
            if status in ("SUCCEEDED", "FAILED", "TIMED_OUT"):
                break
            time.sleep(5)

        if status != "SUCCEEDED":
            raise RuntimeError(f"Apify actor run {run} ended with status: {status}")

        ds_url = (
            f"{self.base}/actor-runs/{run}/dataset/items"
            f"?token={self.token}&clean=true&format=json"
        )
        r = requests.get(ds_url, timeout=60)
        r.raise_for_status()
        raw_items = r.json()
        return [self._normalize(item) for item in raw_items if isinstance(item, dict)]

    def _normalize(self, item: dict[str, Any]) -> JoongnaListing:
        price_text = str(item.get("price", "") or "")
        price = int(re.sub(r"[^\d]", "", price_text.replace(",", "").replace("원", "")))
        return JoongnaListing(
            listing_id=str(item.get("id", "") or item.get("listing_id", "")),
            name=item.get("title", "") or item.get("name", ""),
            price_krw=price,
            price_text=price_text,
            status=_normalize_status(item.get("status", "")),
            wish_count=int(item.get("wish_count", 0) or 0),
            chat_count=int(item.get("chat_count", 0) or 0),
            image_url=item.get("image_url", "") or item.get("thumbnail", ""),
            listed_at=item.get("listed_at", "") or item.get("createdAt", ""),
            url=item.get("url", "") or item.get("link", ""),
            raw=item,
        )


# ---------------------------------------------------------------------------
# Scrapling fallback
# ---------------------------------------------------------------------------

class ScraplingJoongnaScraper:
    """Direct-HTTP fallback scraper for Joongna search pages."""

    def __init__(self, delay: float = 2.0, timeout: int = 20) -> None:
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(_DEFAULT_HEADERS)

    def search(self, query: str) -> list[JoongnaListing]:
        url = f"https://web.joongna.com/search/{quote_plus(query)}"
        time.sleep(self.delay)
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        return self._parse(soup)

    def _parse(self, soup: BeautifulSoup) -> list[JoongnaListing]:
        listings: list[JoongnaListing] = []
        cards = soup.select('a[href*="/product/"]')
        seen: set[str] = set()
        for card in cards:
            href = card.get("href", "")
            if not href or href in seen:
                continue
            # Skip registration/form links
            if "/product/form" in href:
                continue
            seen.add(href)
            full_url = urljoin("https://web.joongna.com/", href)
            # Prefer parent card for richer text extraction
            parent = card.find_parent(["div", "article", "li"])
            if parent:
                title = parent.get_text(" ", strip=True)
                img = parent.find("img")
                image_url = img.get("src", "") if img else ""
            else:
                title = card.get_text(" ", strip=True)
                image_url = ""
            # Extract price from the text block
            price_text = ""
            price_krw = 0
            if parent:
                text_blob = parent.get_text(" ", strip=True)
                m = re.search(r"(\d[\d,]*\s*원|\d+만원)", text_blob)
                if m:
                    price_text = m.group(0).strip()
                    price_krw = _parse_price(price_text)
            if not price_text:
                price_el = card.find(string=re.compile(r"\d"))
                price_text = price_el.strip() if price_el else ""
                price_krw = _parse_price(price_text)
            listing_id = href.split("/")[-1].split("?")[0]
            listings.append(
                JoongnaListing(
                    listing_id=listing_id,
                    name=title,
                    price_krw=price_krw,
                    price_text=price_text,
                    url=full_url,
                    image_url=image_url,
                )
            )
        return listings
