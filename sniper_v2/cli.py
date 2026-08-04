"""Command-line interface for Sniper V2."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow `python sniper_v2/cli.py` from the scripts/ directory
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from sniper_v2.config import SniperConfig
from sniper_v2.scanner import SniperScanner
from sniper_v2.state import SniperState

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sniper_v2",
        description="Sniper V2 — Korean used-market scanner",
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parent.parent / "sniper_llm_config.json"),
        help="Path to sniper_llm_config.json",
    )
    parser.add_argument("--run", action="store_true", help="Execute a full scan run")
    parser.add_argument(
        "--status", action="store_true", help="Print scanner status and last-run info"
    )
    parser.add_argument(
        "--test-daangn",
        nargs="?",
        const="맥북프로",
        help="Smoke-test Daangn scraper (optional query override)",
    )
    parser.add_argument(
        "--test-joongna",
        nargs="?",
        const="맥북프로",
        help="Smoke-test Joongna scraper (optional query override)",
    )
    parser.add_argument(
        "--test-danawa",
        nargs="?",
        const="112758",
        help="Smoke-test Danawa scraper by category code",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Run verification gate on current state only",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable debug logging"
    )
    return parser


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.verbose)

    # Load config
    try:
        cfg = SniperConfig.from_json(args.config)
    except Exception as exc:
        logging.error("Failed to load config: %s", exc)
        return 1

    # Resolve paths relative to config file location
    base_dir = Path(args.config).resolve().parent
    state_path = cfg.resolve_state(base_dir)
    log_path = cfg.resolve_log(base_dir)

    # File handler for log file
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(fh)

    state = SniperState(state_path)
    state.load()
    scanner = SniperScanner(cfg, state)

    if args.status:
        _print_status(state)
        return 0

    if args.test_daangn:
        try:
            results = scanner.test_daangn(args.test_daangn)
            _print_test_results("Daangn", args.test_daangn, results)
            return 0
        except Exception as exc:
            logging.error("Daangn test failed: %s", exc)
            return 1

    if args.test_joongna:
        try:
            results = scanner.test_joongna(args.test_joongna)
            _print_test_results("Joongna", args.test_joongna, results)
            return 0
        except Exception as exc:
            logging.error("Joongna test failed: %s", exc)
            return 1

    if args.test_danawa:
        try:
            results = scanner.test_danawa(args.test_danawa)
            _print_test_results("Danawa", args.test_danawa, results)
            return 0
        except Exception as exc:
            logging.error("Danawa test failed: %s", exc)
            return 1

    if args.verify_only:
        _print_status(state)
        return 0

    if args.run:
        try:
            result = scanner.run()
            print(f"Scan complete: {result.total_new} new, {result.total_scraped} total, "
                  f"{len(result.errors)} errors")
            return 0
        except Exception as exc:
            logging.error("Scan failed: %s", exc)
            return 1

    parser.print_help()
    return 0


def _print_status(state: SniperState) -> None:
    stats = state.get_stats()
    alerts = state.get_recent_alerts(5)
    print(f"State file: {state.path}")
    print(f"Last run:  {state._data.get('last_run', 'never')}")
    print(f"Run count: {state._data.get('run_count', 0)}")
    print(f"Stats:     {stats}")
    print(f"Recent alerts: {len(alerts)}")
    for a in alerts[-3:]:
        print(f"  - {a.get('title', '(untitled)')} | ₩{a.get('price', 0):,}")


def _print_test_results(platform: str, query: str, results: list[dict[str, Any]]) -> None:
    print(f"\n=== {platform} test results for '{query}' ===\n")
    if not results:
        print("(no results)\n")
        return
    for idx, item in enumerate(results, 1):
        print(f"[{idx}] {item.get('title') or item.get('name')}")
        print(f"     Price: {item.get('price') or item.get('price_krw')}")
        print(f"     URL:   {item.get('url')}")
        print()


if __name__ == "__main__":
    sys.exit(main())
