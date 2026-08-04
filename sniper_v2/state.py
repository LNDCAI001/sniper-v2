"""State persistence and dedup logic for Sniper V2."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


KST = timezone(timedelta(hours=9))


def kst_now():
    return datetime.now(KST)


def kst_fmt(dt=None):
    if dt is None:
        dt = kst_now()
    return dt.strftime("%Y-%m-%d %H:%M:%S KST")


def default_state():
    return {
        "seen_ids": [],
        "last_run": None,
        "total_alerts": 0,
        "alert_history": [],
    }


def load_state(state_path):
    """Load state from a JSON file."""
    path = state_path if hasattr(state_path, "read_text") else Path(state_path)
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        # Ensure expected keys exist
        for k, v in default_state().items():
            data.setdefault(k, v if k != "seen_ids" else [])
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default_state()


def save_state(state_path, state):
    """Persist state to JSON."""
    if not hasattr(state_path, "write_text"):
        state_path = Path(state_path)
    state["last_run"] = kst_fmt()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def is_new_listing(state, market, listing_id):
    lid = f"{market}:{listing_id}"
    return lid not in set(state.get("seen_ids", []))


def mark_seen(state, market, listing_id):
    lid = f"{market}:{listing_id}"
    if lid not in state.get("seen_ids", []):
        state["seen_ids"].append(lid)


def record_alert(state, listing):
    """Append to alert history and bump counters."""
    state["total_alerts"] = state.get("total_alerts", 0) + 1
    state.setdefault("alert_history", []).append({
        "time": kst_fmt(),
        "tier": listing.get("tier", "UNKNOWN"),
        "market": listing.get("market", "unknown"),
        "id": listing.get("id", "unknown"),
        "title": listing.get("title", "")[:60],
    })


class SniperState:
    """Object wrapper around the functional state helpers."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._data: dict[str, Any] = default_state()

    def load(self) -> None:
        self._data = load_state(self.path)

    def save(self) -> None:
        save_state(self.path, self._data)

    def is_seen(self, market: str, listing_id: str) -> bool:
        return not is_new_listing(self._data, market, listing_id)

    def mark_seen(self, market: str, listing_id: str) -> None:
        mark_seen(self._data, market, listing_id)

    def add_alert(self, listing: dict[str, Any]) -> None:
        record_alert(self._data, listing)

    def increment_scraped(self, n: int = 1) -> None:
        self._data["total_scraped"] = self._data.get("total_scraped", 0) + n

    def increment_new(self, n: int = 1) -> None:
        self._data["total_new"] = self._data.get("total_new", 0) + n

    def update_last_run(self) -> None:
        self._data["last_run"] = kst_fmt()
        self._data["run_count"] = self._data.get("run_count", 0) + 1

    def record_error(self, msg: str) -> None:
        self._data.setdefault("errors", []).append({
            "time": kst_fmt(),
            "message": msg,
        })

    def get_stats(self) -> dict[str, Any]:
        return {
            "run_count": self._data.get("run_count", 0),
            "total_new": self._data.get("total_new", 0),
            "total_scraped": self._data.get("total_scraped", 0),
            "total_alerts": self._data.get("total_alerts", 0),
            "error_count": len(self._data.get("errors", [])),
        }

    def get_recent_alerts(self, n: int = 5) -> list[dict[str, Any]]:
        return self._data.get("alert_history", [])[-n:]
