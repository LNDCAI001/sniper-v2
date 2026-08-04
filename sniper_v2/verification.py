"""Listing verification for Sniper V2.

Checks:
1. Listing status: active vs sold/reserved/unknown
2. Condition/warranty keywords from title/description
3. Defect/broken-part detection
4. Price sanity vs known baseline range
5. Model match confidence against target query

Returns a structured VerificationResult so scanner.py can filter
before alerts and arbitrage.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class VerificationResult:
    passed: bool
    in_stock: bool
    status: str
    condition: str
    warranty: bool
    defects: list[str]
    model_match_score: float
    flags: list[str]
    raw: dict[str, Any] = field(default_factory=dict)

    def reasons(self) -> list[str]:
        return [f for f in self.flags if f]


# ---------------------------------------------------------------------------
# Keyword dictionaries
# ---------------------------------------------------------------------------

_SOLD_KEYWORDS = [
    "품절", "매진", "품절임박",
    "거래완료", "판매완료", "예약완료", "예약중", "예약가능",
    "sold", "reserved", "sold out", "out of stock", "discontinued",
]

_DEFECT_KEYWORDS = [
    # Korean
    "고장", "파손", "깨짐", "균열", "크랙", "스크래치", "흠집", "찍힘", "변색",
    "오염", "누설", "누수", "무상", "불량", "고열", "다운", "블루스크린", "멈춤",
    "프리징", "지연", "느림", "소음", "팬소리", "코일웜", "털", "먼지", "이물질",
    # Motherboard-specific actual defects
    "bent pin", "bent pins", "노틸러스", "post안됨", "부팅안됨", "메인보드고장", "메인보드 불량",
    # English
    "broken", "cracked", "damaged", "defective", "dead", "no power",
    "artifacts", "screen artifacts", "flickering", "overheating", "overheat",
    "coil whine", "scratched", "scuff", "stained", "water damage",
    "liquid damage", "does not boot", "wont turn on", "won't boot",
    "repair", "repaired", "refurbished", "refurb", "stripped", "missing die",
    "no gpu", "no vram", "empty", "gutted", "rice", "pasta", "box of rocks",
    "fake", "counterfeit", "bricked", "short", "short circuit",
]

_WARRANTY_KEYWORDS = [
    # Korean
    "보증서", "워런티", "as", "a/s", "보증", "잔여보증", "보증기간",
    "제조사보증", "수리보증", "무상수리", "무상as",
    # English
    "warranty", "warranty card", "boxed", "box", "receipt", "original box",
    "w/ warranty", "with warranty", "remaining warranty", "manufacturer warranty",
    "serial", "시리얼", "정품",
]

_NEW_KEYWORDS = [
    "미개봉", "새제품", "새 상품", "신품", "미사용", "개봉안함", "박스만개봉",
    "new", "brand new", "sealed", "unopened", "mint", "미개봉제품",
]

_SCAM_RED_FLAGS = [
    "직거래만", "택배거래만", "안전결제외", "계좌이체만",
    "급매", "급처", "빨리", "서두르세요", "마감임박",
    "다른사람도", "경쟁자", "선입금", "미리입금",
    "외부링크", "카카오톡", "텔레그램",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _contains_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    for k in keywords:
        k_lower = k.lower()
        if len(k_lower) <= 3:
            if re.search(rf"(?<!\w){re.escape(k_lower)}(?!\w)", lowered):
                return True
        elif k_lower in lowered:
            return True
    return False


def _status_from_text(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ("sold", "거래완료", "판매완료", "품절", "매진")):
        return "sold"
    if any(k in t for k in ("reserved", "예약", "예약중")):
        return "reserved"
    if any(k in t for k in ("for sale", "판매중", "selling", "available", "in stock")):
        return "for-sale"
    return "unknown"


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------

@dataclass
class ListingVerifier:
    target_model: str = ""
    known_price_min: int = 0
    known_price_max: int = 10_000_000
    require_warranty: bool = False

    def verify_daangn(self, listing: Any) -> VerificationResult:
        status = str(getattr(listing, "status", "") or "").lower()
        blob = " ".join([
            str(getattr(listing, "title", "") or ""),
            str(getattr(listing, "raw", {}).get("description", "") or ""),
        ])
        return self._evaluate(status, blob, getattr(listing, "price", 0) or 0, {
            "source": "daangn",
            "raw": getattr(listing, "raw", {}),
        })

    def verify_joongna(self, listing: Any) -> VerificationResult:
        status = str(getattr(listing, "status", "") or "").lower()
        blob = " ".join([
            str(getattr(listing, "name", "") or ""),
            str(getattr(listing, "raw", {}).get("description", "") or ""),
        ])
        return self._evaluate(status, blob, getattr(listing, "price_krw", 0) or 0, {
            "source": "joongna",
            "raw": getattr(listing, "raw", {}),
        })

    def verify_yongsanbit(self, listing: Any) -> VerificationResult:
        in_stock = bool(getattr(listing, "in_stock", True))
        blob = str(getattr(listing, "name", "") or "")
        price = getattr(listing, "price_krw", 0) or 0
        if not in_stock:
            return VerificationResult(
                passed=False,
                in_stock=False,
                status="sold",
                condition="unknown",
                warranty=False,
                defects=[],
                model_match_score=0.0,
                flags=["sold-out"],
            )
        return self._evaluate("for-sale", blob, price, {
            "source": "yongsanbit",
            "in_stock": in_stock,
        })

    # ------------------------------------------------------------------
    # Core evaluator
    # ------------------------------------------------------------------

    def _evaluate(
        self,
        status: str,
        blob: str,
        price: int,
        meta: dict[str, Any],
    ) -> VerificationResult:
        flags: list[str] = []
        defects: list[str] = []
        condition = "used"
        warranty = False

        # 1. Status gate
        in_stock = True
        if status in {"sold", "reserved"} or _contains_any(blob, _SOLD_KEYWORDS):
            in_stock = False
            flags.append("sold-out")

        # 2. Condition
        if _contains_any(blob, _NEW_KEYWORDS):
            condition = "new"
        elif _contains_any(blob, ("중고", "used")):
            condition = "used"

        # 3. Warranty
        if _contains_any(blob, _WARRANTY_KEYWORDS):
            warranty = True

        # 4. Defects
        defects = [k for k in _DEFECT_KEYWORDS if _contains_any(blob, [k])]
        if defects:
            flags.append("defects:" + ", ".join(defects[:3]))

        # 5. Price sanity
        if self.known_price_min and price < self.known_price_min:
            flags.append(f"price-below-baseline:{price:,} < {self.known_price_min:,}")
        if self.known_price_max and price > self.known_price_max:
            flags.append(f"price-above-baseline:{price:,} > {self.known_price_max:,}")

        # 6. Scam red flags
        scam_flags = [k for k in _SCAM_RED_FLAGS if _contains_any(blob, [k])]
        if scam_flags:
            flags.append("scam-red-flag:" + ", ".join(scam_flags[:2]))

        # 7. Model match
        model_match_score = self._model_match(blob)

        passed = in_stock and not defects and not scam_flags and model_match_score >= 0.3
        if self.require_warranty:
            passed = passed and warranty

        return VerificationResult(
            passed=passed,
            in_stock=in_stock,
            status=status or _status_from_text(blob),
            condition=condition,
            warranty=warranty,
            defects=defects,
            model_match_score=model_match_score,
            flags=flags,
            raw=meta,
        )

    @staticmethod
    def _model_match(blob: str) -> float:
        if not blob:
            return 0.0
        blob_lower = blob.lower()
        
        # Chipset/brand/model tokens with weights
        strong_matches = [
            "rtx 5090", "rtx5080", "rtx 5070", "rtx 4090", "rtx 4080",
            "5090", "5080", "5070", "4090", "4080",
            "b550", "b450", "b560", "b760", "z790", "x570",
        ]
        medium_matches = [
            "aorus", "rog", "tuf", "suprim", "vantage", "ventus",
            "master", "astral", "solid", "phantom", "gamerock",
            "inno3d", "zotac", "palit", "gainward", "manli",
            "mortar", "bazooka", "steel legend", "itx", "matx", "atx",
        ]
        weak_matches = [
            "gigabyte", "asus", "msi", "evga", "sapphire", "amd",
            "radeon", "rx 9070", "rx 9060", "mainboard", "메인보드",
        ]
        
        strong_hits = sum(1 for m in strong_matches if m in blob_lower)
        medium_hits = sum(1 for m in medium_matches if m in blob_lower)
        weak_hits = sum(1 for m in weak_matches if m in blob_lower)
        
        score = (strong_hits * 1.0 + medium_hits * 0.5 + weak_hits * 0.2) / 3.0
        return min(score, 1.0)
