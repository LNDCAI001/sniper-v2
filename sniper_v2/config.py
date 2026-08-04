"""Configuration loading and defaults for Sniper V2."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PriceThresholds:
    mac_studio_max: int = 5_000_000
    mac_studio_steal: int = 3_500_000
    macbook_max: int = 4_000_000
    macbook_steal: int = 2_800_000
    minipc_max: int = 1_500_000
    minipc_steal: int = 1_000_000
    handheld_max: int = 2_000_000
    handheld_steal: int = 1_200_000
    suspicious_min: int = 500_000

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PriceThresholds:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def dict(self) -> dict[str, Any]:
        return {
            "mac_studio_max": self.mac_studio_max,
            "mac_studio_steal": self.mac_studio_steal,
            "macbook_max": self.macbook_max,
            "macbook_steal": self.macbook_steal,
            "minipc_max": self.minipc_max,
            "minipc_steal": self.minipc_steal,
            "handheld_max": self.handheld_max,
            "handheld_steal": self.handheld_steal,
            "suspicious_min": self.suspicious_min,
        }


@dataclass
class AntiFraud:
    min_seller_age_days: int = 30
    suspicious_price_ratio: float = 0.4
    stock_photo_domains: list[str] = field(default_factory=list)
    known_stock_photo_patterns: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AntiFraud:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def dict(self) -> dict[str, Any]:
        return {
            "min_seller_age_days": self.min_seller_age_days,
            "suspicious_price_ratio": self.suspicious_price_ratio,
            "stock_photo_domains": list(self.stock_photo_domains),
            "known_stock_photo_patterns": list(self.known_stock_photo_patterns),
        }


@dataclass
class SniperConfig:
    name: str = "Sniper V2"
    description: str = ""
    search_terms: list[str] = field(default_factory=list)
    price_thresholds: PriceThresholds = field(default_factory=PriceThresholds)
    anti_fraud: AntiFraud = field(default_factory=AntiFraud)
    output_file: str | Path = "/tmp/sniper_v2_alerts.md"
    log_file: str | Path = "/tmp/sniper_v2.log"
    state_file: str | Path = "/tmp/sniper_v2_state.json"
    title_price_fallback: bool = True
    apify_token: str = ""
    perplexity_token: str = ""
    retry_max: int = 3
    retry_base_delay: float = 2.0
    request_min_interval: float = 1.5
    browser_timeout: int = 30_000
    page_load_timeout: int = 20_000
    daangn_search_url: str = "https://www.daangn.com/kr/buy-sell/?search={query}"
    joongna_search_url: str = "https://web.joongna.com/search/{query}"
    daangn_locations: list[str] = field(default_factory=lambda: ["신림동", "강남구", "송파구", "마포구", "영등포구"])
    cookie_dir: str | Path = "/tmp/sniper_cookies"
    danawa_category: str = "112758"
    yongsanbit_search_terms: list[str] = field(default_factory=list)
    foreign_markets: list[dict[str, Any]] = field(default_factory=list)
    exchange_rates: dict[str, float] = field(default_factory=lambda: {
        "KRW": 1.0,
        "USD": 1350.0,
        "JPY": 9.2,
        "EUR": 1450.0,
    })
    arbitrage_thresholds: dict[str, float] = field(default_factory=lambda: {
        "steal": 15.0,
        "alert": 5.0,
    })

    @classmethod
    def from_json(cls, path: str | Path) -> SniperConfig:
        p = Path(path)
        with open(p, encoding="utf-8") as f:
            data = json.load(f)

        # Convert path-like values to Path
        for key in ("output_file", "log_file", "state_file", "cookie_dir"):
            if key in data and isinstance(data[key], str):
                data[key] = Path(data[key])

        if "price_thresholds" in data:
            data["price_thresholds"] = PriceThresholds.from_dict(data["price_thresholds"])
        if "anti_fraud" in data:
            data["anti_fraud"] = AntiFraud.from_dict(data["anti_fraud"])

        # Apply defaults for missing keys
        defaults = {
            "retry_max": 3,
            "retry_base_delay": 2.0,
            "request_min_interval": 1.5,
            "browser_timeout": 30_000,
            "page_load_timeout": 20_000,
            "daangn_search_url": "https://www.daangn.com/kr/buy-sell/?search={query}",
            "joongna_search_url": "https://web.joongna.com/search/{query}",
            "daangn_locations": ["신림동", "강남구", "송파구", "마포구", "영등포구"],
            "cookie_dir": Path("/tmp/sniper_cookies"),
            "title_price_fallback": True,
            "apify_token": os.getenv("SNIPER_APIFY_TOKEN") or os.getenv("APIFY_TOKEN", ""),
            "perplexity_token": os.getenv("SNIPER_PERPLEXITY_TOKEN", ""),
            "yongsanbit_search_terms": [],
            "foreign_markets": [],
            "exchange_rates": {
                "KRW": 1.0,
                "USD": 1350.0,
                "JPY": 9.2,
                "EUR": 1450.0,
            },
            "arbitrage_thresholds": {
                "steal": 15.0,
                "alert": 5.0,
            },
        }
        for k, v in defaults.items():
            data.setdefault(k, v)

        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "search_terms": list(self.search_terms),
            "price_thresholds": self.price_thresholds.dict(),
            "anti_fraud": self.anti_fraud.dict(),
            "output_file": str(self.output_file),
            "log_file": str(self.log_file),
            "state_file": str(self.state_file),
            "title_price_fallback": self.title_price_fallback,
            "apify_token": self.apify_token,
            "perplexity_token": self.perplexity_token,
            "retry_max": self.retry_max,
            "retry_base_delay": self.retry_base_delay,
            "request_min_interval": self.request_min_interval,
            "browser_timeout": self.browser_timeout,
            "page_load_timeout": self.page_load_timeout,
            "daangn_search_url": self.daangn_search_url,
            "joongna_search_url": self.joongna_search_url,
            "daangn_locations": list(self.daangn_locations),
            "cookie_dir": str(self.cookie_dir),
            "danawa_category": self.danawa_category,
            "yongsanbit_search_terms": list(self.yongsanbit_search_terms),
        }

    def resolve_state(self, base_dir: str | Path) -> Path:
        p = Path(self.state_file)
        if not p.is_absolute():
            p = Path(base_dir) / p
        return p

    def resolve_log(self, base_dir: str | Path) -> Path:
        p = Path(self.log_file)
        if not p.is_absolute():
            p = Path(base_dir) / p
        return p

    def resolve_output(self, base_dir: str | Path) -> Path:
        p = Path(self.output_file)
        if not p.is_absolute():
            p = Path(base_dir) / p
        return p


def load_config(path: str | Path | None = None, env_override: dict[str, str] | None = None) -> dict[str, Any]:
    """Backward-compatible loader returning a plain dict."""
    cfg = SniperConfig.from_json(path) if path else SniperConfig.from_json(
        Path(__file__).resolve().parent / "sniper_v2_config.json"
    )
    if env_override:
        for env_key, cfg_key in env_override.items():
            val = os.environ.get(env_key)
            if val is not None:
                if cfg_key in ("output_file", "log_file", "state_file", "cookie_dir"):
                    setattr(cfg, cfg_key, Path(val))
                else:
                    setattr(cfg, cfg_key, val)
    return cfg.dict()
