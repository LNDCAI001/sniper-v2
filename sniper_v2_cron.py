#!/usr/bin/env python3
"""Cron wrapper for Sniper V2 scanner.

This script is intended to be run by Hermes cron. It executes a full scan
and logs results to the wiki log directory.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure scripts/ is on sys.path for direct execution
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from sniper_v2.config import SniperConfig
from sniper_v2.scanner import SniperScanner
from sniper_v2.state import SniperState


LOG_DIR = _SCRIPTS_DIR.parent / "_hermes_logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "sniper_v2_cron.log"


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    logger = logging.getLogger("sniper_v2.cron")

    try:
        cfg_path = _SCRIPTS_DIR / "sniper_llm_config.json"
        cfg = SniperConfig.from_json(cfg_path)
        base_dir = cfg_path.resolve().parent
        state_path = cfg.resolve_state(base_dir)

        state = SniperState(state_path)
        state.load()
        scanner = SniperScanner(cfg, state)

        logger.info("Starting scheduled scan")
        result = scanner.run(max_workers=4)
        logger.info(
            "Scan complete: %d new / %d total scraped, %d errors",
            result.total_new,
            result.total_scraped,
            len(result.errors),
        )
        return 0 if not result.errors else 1

    except Exception as exc:
        logging.error("Scheduled scan failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
