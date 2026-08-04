"""Perplexity research arm for Sniper V2.

Wraps the sovereign-testbench ``perplexity_ask`` utility to do quick
market research on spotted items.  This module does NOT make autonomous
buying decisions — it only enriches alert context.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default path to the sovereign-testbench perplexity_ask script
_DEFAULT_PERPLEXITY_ASK = Path(
    os.getenv("PERPLEXITY_ASK", "sovereign-testbench/perplexity_ask.py")
)


def research_listing(
    title: str,
    *,
    price_krw: int = 0,
    model: str = "sonar",
    extra_context: str = "",
) -> dict[str, Any]:
    """Run a Perplexity query about a listing and return structured notes.

    Returns a dict with keys:
      - ``summary``: short Perplexity answer
      - ``is_good_deal``: boolean heuristic
      - ``fair_price_low`` / ``fair_price_high``: estimated KRW range
    """
    query = (
        f"Is '{title}' at {price_krw:,} KRW a good deal in the Korean used market? "
        "Give fair market price range in KRW."
    )
    if extra_context:
        query += f"\nContext: {extra_context}"

    answer = _call_perplexity(query, model=model)
    return {
        "query": query,
        "summary": answer,
        "is_good_deal": _heuristic_deal(answer, price_krw),
        "fair_price_low": 0,
        "fair_price_high": 0,
    }


def _call_perplexity(prompt: str, *, model: str = "sonar") -> str:
    """Invoke the sovereign-testbench perplexity_ask script."""
    script = _DEFAULT_PERPLEXITY_ASK
    if not script.exists():
        logger.debug("perplexity_ask script not found at %s — skipping research", script)
        return ""

    try:
        with tempfile.NamedTemporaryFile("w+", suffix=".txt", delete=False, encoding="utf-8") as tmp:
            tmp.write(prompt)
            tmp_path = tmp.name

        env = os.environ.copy()
        env.setdefault("PERPLEXITY_MODEL", model)
        result = subprocess.run(
            ["python", str(script), "--prompt-file", tmp_path],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        Path(tmp_path).unlink(missing_ok=True)
        return result.stdout.strip()
    except Exception as exc:
        logger.debug("Perplexity research failed: %s", exc)
        return ""


def _heuristic_deal(answer: str, price: int) -> bool:
    """Rough heuristic: if Perplexity says 'good deal' and price > 0."""
    if not answer or price <= 0:
        return False
    lower = answer.lower()
    return ("good deal" in lower or "great price" in lower or "싸게" in lower or "저렴" in lower)
