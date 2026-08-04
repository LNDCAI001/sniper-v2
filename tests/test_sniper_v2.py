"""Tests for Sniper V2.

Run with::

    python -m pytest tests/test_sniper_v2.py -v

"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------

from sniper_v2.config import AntiFraud, PriceThresholds, SniperConfig


class TestSniperConfig:
    def test_from_json_loads_defaults(self):
        raw = json.dumps({
            "name": "Test",
            "search_terms": ["a", "b"],
            "price_thresholds": {"mac_studio_max": 4000000},
            "anti_fraud": {"min_seller_age_days": 10},
        })
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(raw)
            p = f.name
        try:
            cfg = SniperConfig.from_json(p)
            assert cfg.name == "Test"
            assert cfg.search_terms == ["a", "b"]
            assert cfg.price_thresholds.mac_studio_max == 4000000
            assert cfg.anti_fraud.min_seller_age_days == 10
        finally:
            os.unlink(p)

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("APIFY_TOKEN", "env-token")
        monkeypatch.setenv("SNIPER_PERPLEXITY_TOKEN", "pplx-env")
        raw = json.dumps({
            "name": "Test",
            "search_terms": [],
            "price_thresholds": {},
            "anti_fraud": {},
        })
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(raw)
            p = f.name
        try:
            cfg = SniperConfig.from_json(p)
            assert cfg.apify_token == "env-token"
            assert cfg.perplexity_token == "pplx-env"
        finally:
            os.unlink(p)

    def test_resolve_paths_absolute(self):
        raw = json.dumps({
            "name": "Test",
            "search_terms": [],
            "price_thresholds": {},
            "anti_fraud": {},
            "output_file": "/tmp/out.md",
            "log_file": "/tmp/log.txt",
            "state_file": "/tmp/state.json",
        })
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(raw)
            p = f.name
        try:
            cfg = SniperConfig.from_json(p)
            base = Path("/base")
            assert cfg.resolve_output(base) == Path("/tmp/out.md")
            assert cfg.resolve_log(base) == Path("/tmp/log.txt")
            assert cfg.resolve_state(base) == Path("/tmp/state.json")
        finally:
            os.unlink(p)


# ---------------------------------------------------------------------------
# State tests
# ---------------------------------------------------------------------------

from sniper_v2.state import SniperState


class TestSniperState:
    def test_thread_safe_file_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "state.json"
            state = SniperState(p)
            state.load()
            state.mark_seen("daangn", "id-1")
            state.mark_seen("daangn", "id-2")
            state.save()
            state2 = SniperState(p)
            state2.load()
            assert state2.is_seen("daangn", "id-1")
            assert state2.is_seen("daangn", "id-2")
            assert not state2.is_seen("joongna", "id-1")

    def test_alerts_and_stats(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "state.json"
            state = SniperState(p)
            state.load()
            state.add_alert({"title": "Item", "price": 1000})
            state.increment_scraped(5)
            state.increment_new(2)
            state.update_last_run()
            state.save()
            state2 = SniperState(p)
            state2.load()
            assert len(state2.get_recent_alerts()) == 1
            stats = state2.get_stats()
            assert stats["total_scraped"] == 5
            assert stats["total_new"] == 2
            assert stats["total_alerts"] == 1


# ---------------------------------------------------------------------------
# Verify tests
# ---------------------------------------------------------------------------

from sniper_v2.verify import VerificationResult, verify_listing


class TestVerifyListing:
    def test_missing_url_fails(self):
        res = verify_listing({"title": "hi"})
        assert not res.passed
        assert any("url" in r for r in res.reasons)

    def test_missing_title_fails(self):
        res = verify_listing({"url": "https://example.com/item"})
        assert not res.passed
        assert any("title" in r.lower() for r in res.reasons)

    def test_registration_page_blocked(self):
        res = verify_listing({"url": "https://daangn.com/signup", "title": "회원가입"})
        assert not res.passed
        assert any("registration" in r.lower() for r in res.reasons)

    def test_stock_photo_domain_blocked(self):
        res = verify_listing({
            "url": "https://www.apple.com/shop/buy-mac-studio",
            "title": "Mac Studio",
            "image": "https://www.apple.com/shop/product/image",
        })
        assert not res.passed
        assert any("stock" in r.lower() or "domain" in r.lower() for r in res.reasons)

    def test_good_listing_passes(self):
        res = verify_listing({
            "url": "https://www.daangn.com/kr/buy-sell/mac-studio-123",
            "title": "맥스튜디오 M2 울트라 128GB",
            "price": 3500000,
            "image": "https://dn5-manual.kakao.com/real/image.jpg",
        })
        assert res.passed


# ---------------------------------------------------------------------------
# Alert tests
# ---------------------------------------------------------------------------

from sniper_v2.alert import write_alerts


class TestAlertWriter:
    def test_write_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "alerts.md"
            listings = [
                {"title": "Mac Studio", "price": 3500000, "url": "https://daangn.com/1"},
            ]
            p = write_alerts(listings, out, platform="daangn")
            assert p.exists()
            content = p.read_text(encoding="utf-8")
            assert "Mac Studio" in content
            assert "₩3,500,000" in content

    def test_empty_listings_writes_placeholder(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "alerts.md"
            p = write_alerts([], out, platform="daangn")
            assert p.exists()
            content = p.read_text(encoding="utf-8")
            assert "No new alerts" in content or "no new" in content.lower()


# ---------------------------------------------------------------------------
# Daangn scraper unit tests (mocked HTTP)
# ---------------------------------------------------------------------------

from sniper_v2.daangn import DaangnScraper, DaangnListing, _parse_price, _extract_json_ld


class TestDaangnHelpers:
    def test_parse_price_won(self):
        assert _parse_price("₩12,500원") == 12500

    def test_parse_price_plain(self):
        assert _parse_price("1,000원") == 1000

    def test_parse_price_empty(self):
        assert _parse_price("") == 0

    def test_parse_price_no_digits(self):
        assert _parse_price("무료") == 0


class TestDaangnScraperMocked:
    @patch("sniper_v2.daangn.requests.Session")
    def test_search_parses_json_ld(self, mock_session_cls):
        html = """
        <html><head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": 1,
                    "item": {
                        "@type": "Product",
                        "name": "Mac Studio",
                        "offers": {
                            "price": "3500000",
                            "url": "https://www.daangn.com/kr/buy-sell/1"
                        }
                    }
                }
            ]
        }
        </script>
        </head><body></body></html>
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        scraper = DaangnScraper()
        results = scraper.search("맥북프로")
        assert len(results) == 1
        assert results[0].title == "Mac Studio"
        assert results[0].price == 3500000
