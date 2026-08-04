"""Daangn (당근마켓) direct HTTP JSON-LD scraper.

Fetches search results and detail pages via plain HTTP requests.
Extracts structured data from JSON-LD / __NEXT_DATA__ embeds when present,
with HTML card parsing as a fallback.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

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
class DaangnListing:
    title: str = ""
    price: int = 0
    price_text: str = ""
    status: str = "unknown"  # for-sale | reserved | sold | unknown
    region: str = ""
    image: str = ""
    url: str = ""
    view_count: int = 0
    chat_count: int = 0
    favorite_count: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "price": self.price,
            "price_text": self.price_text,
            "status": self.status,
            "region": self.region,
            "image": self.image,
            "url": self.url,
            "view_count": self.view_count,
            "chat_count": self.chat_count,
            "favorite_count": self.favorite_count,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json_ld(soup: BeautifulSoup) -> dict[str, Any] | None:
    """Pull the first JSON-LD block if present."""
    tag = soup.find("script", type="application/ld+json")
    if tag and tag.string:
        try:
            data = json.loads(tag.string)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return None


def _extract_next_data(soup: BeautifulSoup) -> dict[str, Any] | None:
    """Pull __NEXT_DATA__ from a Next.js page."""
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag and tag.string:
        try:
            return json.loads(tag.string)
        except json.JSONDecodeError:
            pass
    return None


def _parse_price(text: str) -> int:
    """Convert '₩12,500', '12,500원', or '1580000.0' to int."""
    text = text.strip()
    if not text:
        return 0
    cleaned = re.sub(r"[^\d.]", "", text)
    try:
        return int(float(cleaned)) if cleaned else 0
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------

class DaangnScraper:
    """HTTP-based scraper for Daangn search pages."""

    def __init__(
        self,
        session: requests.Session | None = None,
        delay: float = 1.5,
        timeout: int = 20,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(_DEFAULT_HEADERS)
        self.delay = delay
        self.timeout = timeout

    # ---- search ----------------------------------------------------------

    def search(self, query: str, page: int = 1) -> list[DaangnListing]:
        """Fetch listings for *query* and return parsed results."""
        url = f"https://www.daangn.com/kr/buy-sell/?search={quote_plus(query)}"
        if page > 1:
            url += f"&page={page}"
        return self._parse_search_page(url)

    def _parse_search_page(self, url: str) -> list[DaangnListing]:
        time.sleep(self.delay)
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        listings: list[DaangnListing] = []

        # 1. Try JSON-LD
        json_ld = _extract_json_ld(soup)
        if json_ld:
            listings = self._extract_from_json_ld(json_ld, url)
            if listings:
                return listings

        # 2. Try __NEXT_DATA__
        next_data = _extract_next_data(soup)
        if next_data:
            listings = self._extract_from_next_data(next_data, url)
            if listings:
                return listings

        # 3. Fallback: parse article/card HTML
        listings = self._extract_from_html(soup, url)

        return listings

    # ---- JSON-LD extraction ----------------------------------------------

    def _extract_from_json_ld(
        self, data: dict[str, Any], base_url: str
    ) -> list[DaangnListing]:
        listings: list[DaangnListing] = []
        raw_items = data.get("itemListElement") or []
        items: list[dict[str, Any]] = []
        for elem in raw_items:
            if not isinstance(elem, dict):
                continue
            if elem.get("@type") == "ListItem" and isinstance(elem.get("item"), dict):
                items.append(elem["item"])
            elif isinstance(elem.get("offers"), dict):
                items.append(elem)

        for item in items:
            offers = item.get("offers") or {}
            if isinstance(offers, dict):
                price = _parse_price(str(offers.get("price", item.get("price", ""))))
                url = offers.get("url", item.get("url", ""))
                image = offers.get("image", item.get("image", ""))
            else:
                price = _parse_price(str(item.get("price", "")))
                url = item.get("url", "")
                image = item.get("image", "")
            dl = DaangnListing(
                title=item.get("name", ""),
                price=price,
                price_text=str(offers.get("price", item.get("price", ""))),
                url=url,
                image=image,
                raw=item,
            )
            listings.append(dl)
        return listings

    # ---- __NEXT_DATA__ extraction ----------------------------------------

    def _extract_from_next_data(
        self, data: dict[str, Any], base_url: str
    ) -> list[DaangnListing]:
        listings: list[DaangnListing] = []
        try:
            props = data.get("props", {}).get("pageProps", {})
            # Walk common keys
            candidates = props.get("listings") or props.get("articles") or []
            if not isinstance(candidates, list):
                return listings
            for item in candidates:
                dl = DaangnListing(
                    title=item.get("title", "") or item.get("name", ""),
                    price=item.get("price", 0) or 0,
                    price_text=str(item.get("price", "")),
                    status=item.get("status", "unknown"),
                    region=item.get("region", "") or item.get("address", ""),
                    image=item.get("image", "")
                    or item.get("imageUrl", "")
                    or item.get("thumbnail", ""),
                    url=item.get("url", "") or item.get("slug", ""),
                    view_count=item.get("viewCount", 0) or item.get("views", 0),
                    chat_count=item.get("chatCount", 0) or item.get("chats", 0),
                    favorite_count=item.get("favoriteCount", 0)
                    or item.get("favorites", 0),
                    raw=item,
                )
                if dl.url and not dl.url.startswith("http"):
                    dl.url = urljoin("https://www.daangn.com/", dl.url)
                listings.append(dl)
        except Exception:
            pass
        return listings

    # ---- HTML fallback ---------------------------------------------------

    def _extract_from_html(self, soup: BeautifulSoup, base_url: str) -> list[DaangnListing]:
        listings: list[DaangnListing] = []
        # Look for common card selectors
        cards = soup.select("article[data-testid], .article-card, .feed-card, a[href*='/buy-sell/']")
        seen_urls: set[str] = set()
        for card in cards:
            href = card.get("href", "")
            if not href or "/buy-sell/" not in href:
                # try nested anchor
                a = card.find("a", href=re.compile(r"/buy-sell/"))
                href = a["href"] if a and a.get("href") else ""
            if not href or href in seen_urls:
                continue
            # Skip search/filter/category links
            if any(token in href for token in ("/s/", "category_id", "price=", "search=")):
                continue
            seen_urls.add(href)
            full_url = urljoin("https://www.daangn.com/", href)
            title_el = card.find(["h2", "h3", "strong", "span"])
            title = title_el.get_text(strip=True) if title_el else ""
            price_el = card.find(string=re.compile(r"\d{1,2},\d{3}원|\d+만원|₩"))
            price_text = price_el.strip() if price_el else ""
            price = _parse_price(price_text)
            img_el = card.find("img")
            img = img_el.get("src", "") if img_el else ""
            listings.append(
                DaangnListing(
                    title=title,
                    price=price,
                    price_text=price_text,
                    url=full_url,
                    image=img,
                )
            )
        return listings

    # ---- detail ----------------------------------------------------------

    def fetch_detail(self, slug_or_url: str) -> DaangnListing | None:
        """Fetch a single listing detail page."""
        if not slug_or_url.startswith("http"):
            slug_or_url = f"https://www.daangn.com/kr/buy-sell/{slug_or_url}"
        time.sleep(self.delay)
        resp = self.session.get(slug_or_url, timeout=self.timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        next_data = _extract_next_data(soup)
        if next_data:
            listings = self._extract_from_next_data(next_data, slug_or_url)
            if listings:
                return listings[0]
        return None


def get_region_for_keyword(keyword: str, timeout: int = 15) -> str:
    """Resolve a Korean region keyword to a region name via Daangn API."""
    url = f"https://www.daangn.com/kr/api/v1/regions/keyword?keyword={quote_plus(keyword)}"
    try:
        resp = requests.get(url, timeout=timeout, headers=_DEFAULT_HEADERS)
        resp.raise_for_status()
        data = resp.json()
        # API returns list of regions; take first match
        if isinstance(data, list) and data:
            return data[0].get("name", keyword)
        if isinstance(data, dict):
            regions = data.get("regions", [])
            if regions:
                return regions[0].get("name", keyword)
    except Exception:
        pass
    return keyword
