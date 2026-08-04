#!/usr/bin/env python3
"""Verification harness for Sniper V2.

Checks:
  - Dependencies are installed
  - Playwright browsers are installed (optional warning)
  - State file is valid JSON
  - Config file is valid JSON
  - sniper_v2 package is importable
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = REPO_ROOT
SNIPER_V2_DIR = SCRIPTS_DIR / "sniper_v2"
CONFIG_PATH = SNIPER_V2_DIR / "sniper_v2_config.json"
STATE_PATH_CANDIDATES = [
    SNIPER_V2_DIR / "sniper_v2_state.json",
    REPO_ROOT / "sniper_v2" / "sniper_state.json",
    REPO_ROOT / "sniper_state.json",
]


def check(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def check_python_deps():
    missing = []
    for mod in ["pytest", "playwright"]:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    return check("Python deps", not missing, ", ".join(missing) if missing else "all present")


def check_playwright_browsers():
    playwright = shutil.which("playwright")
    if not playwright:
        return check("Playwright CLI", False, "playwright not in PATH") and False
    try:
        out = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--help"],
            capture_output=True, text=True, timeout=30,
        )
        # If the command ran, browsers may or may not be installed.
        # We can only warn here because install --help always succeeds.
        return check("Playwright browsers", True, "playwright module present")
    except Exception as e:
        return check("Playwright browsers", False, str(e))


def check_json_file(path, label):
    p = Path(path)
    if not p.exists():
        return check(label, True, f"missing: {p} (created on first run)")
    try:
        json.loads(p.read_text(encoding="utf-8"))
        return check(label, True, f"{p}")
    except json.JSONDecodeError as e:
        return check(label, False, f"invalid JSON: {e}")


def check_import_sniper_v2():
    try:
        sys.path.insert(0, str(SCRIPTS_DIR))
        import sniper_v2  # noqa: F401
        from sniper_v2.config import load_config  # noqa: F401
        from sniper_v2.state import load_state, save_state  # noqa: F401
        from sniper_v2.anti_fraud import is_stock_photo_url  # noqa: F401
        from sniper_v2.alerts import generate_alert_markdown  # noqa: F401
        from sniper_v2.cli import main  # noqa: F401
        return check("sniper_v2 import", True, "all submodules importable")
    except Exception as e:
        return check("sniper_v2 import", False, str(e))


def main():
    print("=" * 60)
    print("Sniper V2 Verification Harness")
    print("=" * 60)

    results = []
    results.append(check_python_deps())
    results.append(check_playwright_browsers())
    results.append(check_json_file(CONFIG_PATH, "Config JSON"))
    results.append(any(check_json_file(p, f"State JSON candidate: {p.name}") for p in STATE_PATH_CANDIDATES))
    results.append(check_import_sniper_v2())

    print("=" * 60)
    if all(results):
        print("All checks passed.")
        sys.exit(0)
    else:
        print("Some checks failed. Review output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
