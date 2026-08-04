"""Main scanner orchestrator for Sniper V2.

Coordinates config loading, state management, platform scrapers,
verification gating, and alert generation.
"""

from __future__ import annotations

import logging
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sniper_v2.alert import write_alerts
from sniper_v2.arbitrage import (
    build_baselines_from_danawa,
    build_baselines_from_foreign_markets,
    evaluate_arbitrage,
)
from sniper_v2.config import SniperConfig
from sniper_v2.daangn import DaangnScraper, DaangnListing, get_region_for_keyword
from sniper_v2.danawa import DanawaCliScraper, DanawaScraper, DanawaListing as DanawaListingModel
from sniper_v2.exchange import get_exchange_rates as load_exchange_rates
from sniper_v2.joongna import (
    ApifyJoongnaScraper,
    JoongnaListing,
    ScraplingJoongnaScraper,
)
from sniper_v2.state import SniperState
from sniper_v2.verify import VerificationResult as VerifyResult
from sniper_v2.verify import verify_listing
from sniper_v2.verification import ListingVerifier, VerificationResult as ListingVerificationResult
from sniper_v2.yesmem_memory import YesMemMemory
from sniper_v2.yongsanbit import YongSanBitScraper

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ScanResult:
    daangn_new: list[dict[str, Any]] = field(default_factory=list)
    joongna_new: list[dict[str, Any]] = field(default_factory=list)
    danawa_new: list[dict[str, Any]] = field(default_factory=list)
    yongsanbit_new: list[dict[str, Any]] = field(default_factory=list)
    arbitrage_new: list[dict[str, Any]] = field(default_factory=list)
    daangn_total: int = 0
    joongna_total: int = 0
    danawa_total: int = 0
    yongsanbit_total: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_new(self) -> int:
        return len(self.daangn_new) + len(self.joongna_new) + len(self.danawa_new) + len(self.yongsanbit_new) + len(self.arbitrage_new)

    @property
    def total_scraped(self) -> int:
        return self.daangn_total + self.joongna_total + self.danawa_total + self.yongsanbit_total


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class SniperScanner:
    """Coordinates a full scan run."""

    def __init__(self, config: SniperConfig, state: SniperState) -> None:
        self.cfg = config
        self.state = state
        self.memory = YesMemMemory()
        self.daangn = DaangnScraper()
        self.apify_joongna = ApifyJoongnaScraper(token=config.apify_token)
        self.scrapling_joongna = ScraplingJoongnaScraper()
        self.danawa = DanawaScraper()
        self.yongsanbit = YongSanBitScraper()
        self.verifier = ListingVerifier(
            target_model=" ".join(config.search_terms[:3]),
            known_price_min=getattr(config.price_thresholds, "suspicious_min", 500_000),
            known_price_max=20_000_000,
        )

    # ---- public API ------------------------------------------------------

    def run(self, max_workers: int = 4) -> ScanResult:
        """Execute a full scan across all configured search terms."""
        result = ScanResult()
        terms = self.cfg.search_terms
        logger.info("Starting scan with %d search terms", len(terms))

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {}
            for term in terms:
                futures[pool.submit(self._scan_daangn, term)] = ("daangn", term)
                futures[pool.submit(self._scan_joongna, term)] = ("joongna", term)
                futures[pool.submit(self._scan_danawa, term)] = ("danawa", term)

            # Scan YongSanBit once per run for new-market baseline
            yb_terms = getattr(self.cfg, "yongsanbit_search_terms", None) or terms[:1]
            for term in yb_terms:
                futures[pool.submit(self._scan_yongsanbit, term)] = ("yongsanbit", term)

            for future in as_completed(futures):
                platform, term = futures[future]
                try:
                    items = future.result()
                except Exception as exc:
                    msg = f"{platform} '{term}': {exc}"
                    logger.exception(msg)
                    result.errors.append(msg)
                    self.state.record_error(msg)
                    continue

                if platform == "daangn":
                    result.daangn_total += len(items)
                    new = self._dedupe_and_verify("daangn", items)
                    result.daangn_new.extend(new)
                elif platform == "joongna":
                    result.joongna_total += len(items)
                    new = self._dedupe_and_verify("joongna", items)
                    result.joongna_new.extend(new)
                elif platform == "danawa":
                    result.danawa_total += len(items)
                    new = self._dedupe_and_verify("danawa", items)
                    result.danawa_new.extend(new)
                else:
                    result.yongsanbit_total += len(items)
                    new = self._dedupe_and_verify("yongsanbit", items)
                    result.yongsanbit_new.extend(new)

        # Write alerts
        self._write_alerts(result)

        # Evaluate arbitrage
        self._evaluate_arbitrage(result)

        # Update state
        self.state.update_last_run()
        self.state.save()
        self.memory.log_run(result.__dict__)

        logger.info(
            "Scan complete: %d new / %d total scraped, %d errors",
            result.total_new,
            result.total_scraped,
            len(result.errors),
        )
        return result

    def test_daangn(self, query: str = "맥북프로") -> list[dict[str, Any]]:
        """Quick smoke-test for Daangn scraper."""
        items = self.daangn.search(query)
        return [item.to_dict() for item in items[:5]]

    def test_joongna(self, query: str = "맥북프로") -> list[dict[str, Any]]:
        """Quick smoke-test for Joongna scraper (Apify first, then Scrapling)."""
        try:
            items = self.apify_joongna.search(query)
            return [item.to_dict() for item in items[:5]]
        except RuntimeError as exc:
            logger.info("Apify unavailable (%s) — trying Scrapling", exc)
            items = self.scrapling_joongna.search(query)
            return [item.to_dict() for item in items[:5]]

    def test_danawa(self, query: str = "112758") -> list[dict[str, Any]]:
        """Quick smoke-test for Danawa scraper.

        Prefers the local ``danawa`` CLI for keyword search when available.
        Falls back to category-page HTTP scraping for numeric category codes.
        """
        cli = DanawaCliScraper()
        if cli.available():
            items = cli.search(query)
            if items:
                return [item.to_dict() for item in items[:5]]

        # Fallback: treat query as category code if it is numeric
        if query.isdigit():
            items = self.danawa.search_by_category(query)
            return [item.to_dict() for item in items[:5]]

        # Last resort: generic keyword search via HTTP
        items = self.danawa.search_by_keyword(query)
        return [item.to_dict() for item in items[:5]]

    # ---- internal helpers ------------------------------------------------

    def _scan_daangn(self, term: str) -> list[DaangnListing]:
        return self.daangn.search(term)

    def _scan_joongna(self, term: str) -> list[JoongnaListing]:
        try:
            return self.apify_joongna.search(term)
        except RuntimeError as exc:
            logger.info("Apify unavailable (%s) — falling back to Scrapling", exc)
            return self.scrapling_joongna.search(term)

    def _scan_danawa(self, query: str) -> list[DanawaListingModel]:
        # Prefer keyword search via CLI when possible
        cli = DanawaCliScraper()
        if cli.available() and not query.isdigit():
            items = cli.search(query)
            if items:
                return items

        # Fallback to category or HTTP keyword search
        if query.isdigit():
            return self.danawa.search_by_category(query)
        return self.danawa.search_by_keyword(query)

    def _scan_yongsanbit(self, term: str) -> list[YongSanListing]:
        items = self.yongsanbit.search_gpu()
        # Filter out sold-out listings
        return [item for item in items if getattr(item, "in_stock", True)]

    def _dedupe_and_verify(
        self, platform: str, items: list[Any]
    ) -> list[dict[str, Any]]:
        new_items: list[dict[str, Any]] = []
        for item in items:
            listing_dict = item.to_dict() if hasattr(item, "to_dict") else item
            lid = (
                listing_dict.get("url")
                or listing_dict.get("listing_id")
                or listing_dict.get("title", "")
            )
            if not lid:
                continue
            if self.state.is_seen(platform, lid):
                continue

            vresult = verify_listing(
                listing_dict,
                anti_fraud=self.cfg.anti_fraud.dict(),
                price_thresholds=self.cfg.price_thresholds.dict(),
                platform=platform,
            )
            if not vresult.passed:
                logger.debug(
                    "Filtered out %s: %s", lid, "; ".join(vresult.reasons)
                )
                continue

            # Listing-level sold/defect/warranty/model-match checks
            object_result = self._verify_listing_object(platform, item)
            if not object_result.passed:
                logger.debug(
                    "Filtered out %s: %s", lid, "; ".join(object_result.flags)
                )
                continue

            self.state.mark_seen(platform, lid)
            self.state.increment_new()
            listing_dict.setdefault("platform", platform)
            listing_dict.setdefault("timestamp", _now_iso())
            listing_dict.setdefault("verification", object_result.raw)
            listing_dict.setdefault("condition", object_result.condition)
            listing_dict.setdefault("warranty", object_result.warranty)
            listing_dict.setdefault("defects", object_result.defects)
            listing_dict.setdefault("model_match_score", object_result.model_match_score)
            self.state.add_alert(listing_dict)
            new_items.append(listing_dict)
        self.state.increment_scraped(len(items))
        return new_items

    def _verify_listing_object(self, platform: str, item: Any) -> ListingVerificationResult:
        if platform == "daangn":
            return self.verifier.verify_daangn(item)
        if platform == "joongna":
            return self.verifier.verify_joongna(item)
        if platform == "danawa":
            title = getattr(item, "name", "") or ""
            price = getattr(item, "minPrice", 0) or 0
            return self.verifier._evaluate(
                "for-sale",
                title,
                price,
                {"source": "danawa", "pcode": getattr(item, "productCode", "")},
            )
        if platform == "yongsanbit":
            return self.verifier.verify_yongsanbit(item)
        return self.verifier._evaluate(
            getattr(item, "status", "") or "unknown",
            getattr(item, "title", "") or getattr(item, "name", "") or "",
            getattr(item, "price", 0) or getattr(item, "price_krw", 0) or 0,
            {"source": platform},
        )

    def _write_alerts(self, result: ScanResult) -> None:
        base = Path(self.cfg.output_file).parent
        if result.daangn_new:
            write_alerts(
                result.daangn_new,
                self.cfg.resolve_output(base),
                platform="daangn",
                query=", ".join(self.cfg.search_terms[:3]),
            )
        if result.joongna_new:
            llm_path = Path(self.cfg.output_file).parent / "SNIPER_ALERTS_LLM.md"
            write_alerts(
                result.joongna_new,
                str(llm_path),
                platform="joongna",
                query=", ".join(self.cfg.search_terms[:3]),
            )
        if result.danawa_new:
            danawa_path = Path(self.cfg.output_file).parent / "SNIPER_ALERTS_DANAWA.md"
            write_alerts(
                result.danawa_new,
                str(danawa_path),
                platform="danawa",
                query=f"category:{self.cfg.danawa_category}",
            )
        if result.arbitrage_new:
            arb_path = Path(self.cfg.output_file).parent / "SNIPER_ARBITRAGE.md"
            write_alerts(
                result.arbitrage_new,
                str(arb_path),
                platform="arbitrage",
                query=", ".join(self.cfg.search_terms[:3]),
            )
        if result.yongsanbit_new:
            yb_path = Path(self.cfg.output_file).parent / "SNIPER_ALERTS_YONGSANBIT.md"
            write_alerts(
                result.yongsanbit_new,
                str(yb_path),
                platform="yongsanbit",
                query=", ".join(self.cfg.search_terms[:3]),
            )

    def _evaluate_arbitrage(self, result: ScanResult) -> None:
        baselines: list[Any] = []
        baselines.extend(build_baselines_from_danawa(result.danawa_new, region="KR", source="danawa"))
        # YongSanBit as authoritative new-market floor
        yb_baselines = _build_yongsanbit_baselines(result.yongsanbit_new)
        baselines.extend(yb_baselines)
        foreign = getattr(self.cfg, "foreign_markets", None) or []
        if foreign:
            try:
                live_rates = load_exchange_rates(["USD", "JPY", "EUR"], quote="KRW")
            except Exception as exc:
                logger.debug("Live exchange rate fetch failed: %s", exc)
                live_rates = getattr(self.cfg, "exchange_rates", None) or {}
            cfg_rates = dict(getattr(self.cfg, "exchange_rates", None) or {})
            cfg_rates.setdefault("KRW", 1.0)
            cfg_rates.update({k: v for k, v in live_rates.items() if v > 0})
            exchange_rates = cfg_rates
        else:
            exchange_rates = getattr(self.cfg, "exchange_rates", None)
        baselines.extend(build_baselines_from_foreign_markets(foreign, exchange_rates))
        if not baselines:
            return
        candidates = result.daangn_new + result.joongna_new
        if not candidates:
            return
        opportunities = evaluate_arbitrage(
            candidates,
            baselines,
            exchange_rates=exchange_rates,
            thresholds=getattr(self.cfg, "arbitrage_thresholds", None),
        )
        if not opportunities:
            return
        kept: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for opp in opportunities:
            lid = opp.listing.get("url") or opp.listing.get("listing_id") or ""
            if not lid or lid in seen_ids:
                continue
            seen_ids.add(lid)
            if opp.signal not in ("steal", "alert"):
                continue
            self.state.mark_seen("arbitrage", lid)
            self.state.increment_new()
            opp.listing.setdefault("platform", "arbitrage")
            opp.listing.setdefault("timestamp", _now_iso())
            self.state.add_alert(opp.listing)
            kept.append(opp.to_dict())
        result.arbitrage_new = kept
        if kept:
            logger.info("Arbitrage opportunities: %d", len(kept))


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _build_yongsanbit_baselines(yongsanbit_listings: list[dict[str, Any]]) -> list[Any]:
    """Convert YongSanBit listings into PriceBaseline objects."""
    from sniper_v2.arbitrage import PriceBaseline
    baselines: list[Any] = []
    for item in yongsanbit_listings:
        name = item.get("name") or item.get("title") or ""
        price = item.get("price_krw") or item.get("price") or 0
        if not name or price <= 0:
            continue
        baselines.append(
            PriceBaseline(
                model_key=name.strip(),
                region="KR",
                price=price,
                source="yongsanbit",
                url=item.get("url", ""),
            )
        )
    return baselines
