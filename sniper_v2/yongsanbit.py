"""YongSan Bit System (용산비트시스템) price scraper.

Extracts GPU/new hardware prices from yongsanbit.co.kr product listings.
Used as a new-market price baseline for Danawa-layer-1 arbitrage.

Sold-out items are detected and filtered out using:
- list-page sold-out badges/indicators
- detail-page `sit_ov_soldout` messages
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

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

_BASE_URL = "https://www.yongsanbit.co.kr/yc5/shop/"

_SOLD_OUT_KEYWORDS = [
    "품절",
    "매진",
    "재고가 부족하여 구매할 수 없습니다",
    "soldout",
    "sold out",
    "out of stock",
]

_SOLD_OUT_IMAGES = [
    "icon_soldout",
    "soldout",
    "no_stock",
]


@dataclass
class YongSanListing:
    it_id: str = ""
    name: str = ""
    price_krw: int = 0
    price_text: str = ""
    url: str = ""
    in_stock: bool = True
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "it_id": self.it_id,
            "name": self.name,
            "price_krw": self.price_krw,
            "price_text": self.price_text,
            "url": self.url,
            "in_stock": self.in_stock,
        }


class YongSanBitScraper:
    """Scrapes yongsanbit.co.kr product listings."""

    def __init__(self, session=None, delay=1.0, timeout=20) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(_DEFAULT_HEADERS)
        self.delay = delay
        self.timeout = timeout

    def search_gpu(self, page=1) -> list[YongSanListing]:
        """Fetch GPU listings from category 7010s0, sorted by price asc."""
        url = (
            f"{_BASE_URL}list.php"
            f"?ca_id=7010s0&page={page}&sort=it_price&sortodr=asc"
        )
        return self._parse_list_page(url)

    def search_by_category(self, ca_id="7010s0", page=1, sort="it_price", sortodr="asc") -> list[YongSanListing]:
        """Generic category search."""
        url = (
            f"{_BASE_URL}list.php"
            f"?ca_id={ca_id}&page={page}&sort={sort}&sortodr={sortodr}"
        )
        return self._parse_list_page(url)

    def _parse_list_page(self, url: str) -> list[YongSanListing]:
        import time as _time
        _time.sleep(self.delay)
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        return self._extract_items(soup, url)

    def _extract_items(self, soup: BeautifulSoup, base_url: str) -> list[YongSanListing]:
        listings: list[YongSanListing] = []

        # Find all item-name divs
        name_divs = soup.find_all("div", class_="item-name")
        for name_div in name_divs:
            try:
                listing = self._parse_item(name_div, base_url)
                if listing:
                    listings.append(listing)
            except Exception as exc:
                logger.debug("Failed to parse YongSan item: %s", exc)

        return listings

    def _parse_item(self, name_div, base_url: str) -> YongSanListing | None:
        # Get name from item-name div
        name = name_div.get_text(" ", strip=True)
        if not name:
            return None

        # Get link from item-name div
        link = name_div.find("a", href=True)
        if not link:
            return None

        href = link.get("href", "")
        it_id = ""
        m = re.search(r"it_id=([^&]+)", href)
        if m:
            it_id = m.group(1)

        # Build full URL
        if href.startswith("./"):
            url = _BASE_URL + href[2:]
        elif href.startswith("/"):
            url = "https://www.yongsanbit.co.kr" + href
        else:
            url = href

        # Get price from sibling div
        price = 0
        price_text = ""
        parent = name_div.parent
        if parent:
            price_div = parent.find("div", class_="item-price")
            if price_div:
                price_text = price_div.get_text(" ", strip=True)
                # Extract number
                nums = re.findall(r"[\d,]+", price_text)
                if nums:
                    price = int(nums[0].replace(",", ""))

        # Detect sold-out status from surrounding item container
        in_stock = True
        container = parent if parent else name_div
        container_text = container.get_text(" ", strip=True)
        container_html = str(container)

        # Check for sold-out keywords in container text
        for keyword in _SOLD_OUT_KEYWORDS:
            if keyword in container_text.lower():
                in_stock = False
                break

        # Check for sold-out image indicators
        if in_stock:
            for img_keyword in _SOLD_OUT_IMAGES:
                if img_keyword in container_html.lower():
                    in_stock = False
                    break

        # If still in stock, verify via detail page
        if in_stock and url:
            in_stock = self._verify_detail_stock(url)

        if not in_stock:
            logger.debug("Filtered sold-out item: %s", name)

        return YongSanListing(
            it_id=it_id,
            name=name,
            price_krw=price,
            price_text=price_text,
            url=url,
            in_stock=in_stock,
        )

    def _verify_detail_stock(self, url: str) -> bool:
        """Verify stock status from product detail page."""
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code != 200:
                return True  # Can't verify, assume in stock

            # Check for sold-out message element
            soldout_el = BeautifulSoup(resp.text, "html.parser").find("p", id="sit_ov_soldout")
            if soldout_el:
                return False

            # Check for sold-out text patterns
            text_lower = resp.text.lower()
            for keyword in _SOLD_OUT_KEYWORDS:
                if keyword in text_lower:
                    return False

            return True
        except Exception as exc:
            logger.debug("Detail page stock check failed for %s: %s", url, exc)
            return True  # On error, assume in stock


def _parse_price(text: str) -> int:
    cleaned = text.replace(",", "").replace("원", "").replace("₩", "").strip()
    cleaned = re.sub(r"[^\d]", "", cleaned)
    return int(cleaned) if cleaned else 0
