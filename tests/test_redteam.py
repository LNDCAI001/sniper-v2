"""Red-team adversarial tests for ListingVerifier.

These listings attempt common Korean used-market scam/bypass patterns:
- Sold/reserved status hidden in title
- Mining repack disguised as condition grade
- Payment bypass / direct-transfer pressure
- Model-mismatch with shared tokens (ASUS, mainboard, etc.)
- Price-anomaly bait
"""

import pytest
from sniper_v2.verification import ListingVerifier


@pytest.fixture()
def verifier():
    return ListingVerifier(
        target_model="B550",
        known_price_min=100_000,
        known_price_max=400_000,
        require_warranty=False,
    )


def _daangn_listing(title: str, price: int, status: str = "for-sale", description: str = ""):
    class Listing:
        pass
    l = Listing()
    l.title = title
    l.price = price
    l.status = status
    l.raw = {"description": description}
    return l


def _joongna_listing(name: str, price: int, status: str = "판매중", description: str = ""):
    class Listing:
        pass
    l = Listing()
    l.name = name
    l.price_krw = price
    l.status = status
    l.raw = {"description": description}
    return l


class TestRedTeamBypass:
    def test_sold_hidden_in_title(self, verifier):
        listing = _daangn_listing("ASUS B550 sold complete", 200_000)
        result = verifier.verify_daangn(listing)
        assert result.passed is False
        assert any("sold" in f.lower() for f in result.flags)

    def test_reserved_in_title(self, verifier):
        listing = _joongna_listing("B550 예약중", 150_000, status="판매중")
        result = verifier.verify_joongna(listing)
        assert result.passed is False
        assert any("sold" in f.lower() for f in result.flags)

    def test_payment_bypass_keywords(self, verifier):
        listing = _daangn_listing("B550 빨리 계좌이체만 가능", 180_000)
        result = verifier.verify_daangn(listing)
        assert result.passed is False
        assert any("scam" in f.lower() for f in result.flags)

    def test_mining_repack_keyword(self, verifier):
        listing = _joongna_listing("B550 채굴했어요 상태상", 90_000)
        result = verifier.verify_joongna(listing)
        assert result.passed is False
        flags = " ".join(result.flags).lower()
        assert "scam" in flags or "defect" in flags or "price-below" in flags

    def test_defect_keyword_detection(self, verifier):
        listing = _daangn_listing("B550 메인보드고장/부팅안됨", 120_000)
        result = verifier.verify_daangn(listing)
        assert result.passed is False
        assert any("defect" in f.lower() for f in result.flags)

    def test_model_mismatch_weak_token_only(self, verifier):
        listing = _daangn_listing("ASUS 메인보드 상태상", 200_000)
        result = verifier.verify_daangn(listing)
        assert result.model_match_score < 0.3 or result.passed is False

    def test_price_above_baseline_flag(self, verifier):
        listing = _joongna_listing("B550 itx 완품", 999_999)
        result = verifier.verify_joongna(listing)
        assert any("price-above" in f.lower() for f in result.flags)

    def test_clean_listing_passes(self, verifier):
        listing = _daangn_listing("ASUS ROG STRIX B550-I GAMING WIFI 미개봉", 150_000)
        result = verifier.verify_daangn(listing)
        assert result.passed is True
        assert result.condition_grade == ""
        assert result.condition == "new"

    def test_condition_grade_extracted(self, verifier):
        listing = _joongna_listing("B550 S급 상태상", 180_000)
        result = verifier.verify_joongna(listing)
        assert result.condition_grade == "S"
        assert result.passed is True
