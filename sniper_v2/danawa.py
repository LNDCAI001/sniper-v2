"""Danawa (다나와) price comparison scraper.

Primary path: local ``danawa`` CLI when available.
Fallback: direct HTTP + BeautifulSoup against ``prod.danawa.com``.

Extracts:
  pcode, name, price_krw, price_text, category, url, image
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

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
class DanawaListing:
    pcode: str = ""
    name: str = ""
    price_krw: int = 0
    price_text: str = ""
    category: str = ""
    url: str = ""
    image: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pcode": self.pcode,
            "name": self.name,
            "price_krw": self.price_krw,
            "price_text": self.price_text,
            "category": self.category,
            "url": self.url,
            "image": self.image,
        }


def _parse_price(text: str) -> int:
    cleaned = text.replace(",", "").replace("원", "").replace("₩", "").strip()
    cleaned = re.sub(r"[^\d]", "", cleaned)
    return int(cleaned) if cleaned else 0


class DanawaCliScraper:
    """Primary Danawa scraper using the local ``danawa`` CLI."""

    def __init__(self, delay: float = 1.5, timeout: int = 20) -> None:
        self.delay = delay
        self.timeout = timeout
        self._cli = _resolve_danawa_cli()

    def available(self) -> bool:
        return self._cli is not None

    def search(self, keyword: str) -> list[DanawaListing]:
        if not self._cli:
            return []
        cmd = [
            self._cli,
            "search",
            keyword,
            "--format",
            "json",
            "--fields",
            "productName,minPrice,productCode,reviewCount,imageUrl",
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except Exception as exc:
            logger.debug("danawa CLI search failed: %s", exc)
            return []

        stdout = proc.stdout.strip()
        if not stdout:
            logger.debug("danawa CLI returned empty stdout for %s", keyword)
            return []

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as exc:
            logger.debug("danawa CLI JSON parse failed: %s — %s", exc, stdout[:200])
            return []

        items = data.get("items") or []
        listings: list[DanawaListing] = []
        for item in items:
            name = (item.get("productName") or "").strip()
            price = item.get("minPrice") or 0
            pcode = str(item.get("productCode") or "")
            if not name or not pcode:
                continue
            listings.append(
                DanawaListing(
                    pcode=pcode,
                    name=re.sub(r"<[^>]+>", " ", name),
                    price_krw=int(price),
                    price_text=f"{int(price):,}원",
                    url=f"https://prod.danawa.com/info/?pcode={pcode}",
                    image=item.get("imageUrl") or "",
                    raw=item,
                )
            )
        return listings


class DanawaScraper:
    """HTTP scraper for Danawa price comparison pages."""

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

    def search_by_category(self, category_code: str) -> list[DanawaListing]:
        """Fetch listings from a Danawa category page."""
        url = f"https://prod.danawa.com/list/?cate={category_code}"
        return self._parse_list_page(url)

    def search_by_keyword(self, keyword: str) -> list[DanawaListing]:
        """Search Danawa by keyword."""
        url = f"https://search.danawa.com/main/search?keyword={keyword}"
        return self._parse_list_page(url)

    def get_price_history(self, pcode: str) -> dict[str, Any]:
        """Get price history for a specific product."""
        url = f"https://prod.danawa.com/info/?pcode={pcode}"
        time.sleep(self.delay)
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        result: dict[str, Any] = {
            "pcode": pcode,
            "name": "",
            "current_price": 0,
            "price_history": [],
        }

        # Extract from JSON-LD
        ld = soup.find("script", type="application/ld+json")
        if ld and ld.string:
            try:
                data = json.loads(ld.string)
                if isinstance(data, dict) and data.get("@type") == "Product":
                    result["name"] = data.get("name", "")
                    offers = data.get("offers", {})
                    if isinstance(offers, dict):
                        result["current_price"] = _parse_price(str(offers.get("price", "")))
            except Exception:
                pass

        # Extract price from page text
        text = soup.get_text(" ", strip=True)
        prices = re.findall(r"[\d,]+원", text)
        if prices and not result["current_price"]:
            result["current_price"] = _parse_price(prices[0])

        return result

    def _parse_list_page(self, url: str) -> list[DanawaListing]:
        time.sleep(self.delay)
        resp = self.session.get(url, timeout=self.timeout)
        if resp.status_code == 404:
            logger.debug("Danawa list page 404: %s", url)
            return []
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        return self._extract_items(soup, url)

    def _extract_items(self, soup: BeautifulSoup, base_url: str) -> list[DanawaListing]:
        listings: list[DanawaListing] = []
        items = soup.select(".prod_item")
        for item in items:
            try:
                listing = self._parse_item(item, base_url)
                if listing:
                    listings.append(listing)
            except Exception as exc:
                logger.debug("Failed to parse Danawa item: %s", exc)
        return listings

    def _parse_item(self, item: BeautifulSoup, base_url: str) -> DanawaListing | None:
        # Name
        name_el = item.select_one(".prod_name a")
        if not name_el:
            return None
        name = name_el.get_text(" ", strip=True)

        # URL and pcode
        href = name_el.get("href", "")
        pcode = ""
        if "pcode=" in href:
            parsed = urlparse(href)
            qs = parse_qs(parsed.query)
            pcode = qs.get("pcode", [""])[0]
        if not pcode:
            pcode_attr = item.get("data-productcodeforshoppingmallad", "")
            if pcode_attr:
                pcode = pcode_attr

        # Price
        text = item.get_text(" ", strip=True)
        price = 0
        m = re.search(r"등록\s+최저가\s*([\d,]+)\s*원", text)
        if not m:
            m = re.search(r"최저가\s*([\d,]+)\s*원", text)
        if not m:
            m = re.search(r"([\d,]+)\s*원", text)
        if m:
            price = _parse_price(m.group(1))

        # Image
        img_el = item.select_one("img")
        image = img_el.get("src", "") if img_el else ""

        # Category from URL
        category = ""
        if "cate=" in base_url:
            parsed = urlparse(base_url)
            qs = parse_qs(parsed.query)
            category = qs.get("cate", [""])[0]

        return DanawaListing(
            pcode=pcode,
            name=name,
            price_krw=price,
            price_text=m.group(1) if m else "",
            category=category,
            url=href,
            image=image,
            raw={"text": text[:500]},
        )


def _resolve_danawa_cli() -> str | None:
    candidates: list[str] = []
    env = os.environ.get("DANAWA_CLI")
    if env:
        candidates.append(env)
    candidates.extend([
        shutil.which("danawa"),
        os.path.expandvars(r"%APPDATA%\npm\danawa"),
        os.path.expandvars(r"%LOCALAPPDATA%\npm\danawa"),
        "/c/Users/Dachi/AppData/Roaming/npm/danawa",
        "C:/Users/Dachi/AppData/Roaming/npm/danawa",
    ])
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None
