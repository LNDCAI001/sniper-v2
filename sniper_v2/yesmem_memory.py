"""YesMem memory integration for Sniper V2.

Wraps the YesMem MCP tools to persist learned facts about listings,
seller patterns, and scanner performance across sessions.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class YesMemMemory:
    """Optional YesMem persistence layer.

    If YesMem tools are available, this class stores scanner memories.
    Otherwise it degrades to a no-op so the scanner keeps running.
    """

    def __init__(self, project: str = "sniper-v2") -> None:
        self.project = project
        self._available = self._check_available()

    def _check_available(self) -> bool:
        try:
            from yesmem_tools import remember, search  # noqa: F401

            return True
        except ImportError:
            logger.debug("yesmem_tools not available — memory disabled")
            return False

    def save_fact(self, key: str, value: Any) -> None:
        """Persist a fact via YesMem if available."""
        if not self._available:
            return
        try:
            from yesmem_tools import remember  # type: ignore

            remember(
                project=self.project,
                category="scanner-fact",
                key=key,
                value=value,
                ts=datetime.now().isoformat(),
            )
        except Exception as exc:
            logger.debug("YesMem save_fact failed: %s", exc)

    def remember_listing(self, listing_id: str, platform: str, notes: str) -> None:
        """Persist a listing memory."""
        self.save_fact(f"listing:{platform}:{listing_id}", notes)

    def log_run(self, stats: dict[str, Any]) -> None:
        """Persist run statistics."""
        self.save_fact(f"run:{datetime.now().date().isoformat()}", stats)

    def recall(self, key: str) -> Any | None:
        """Retrieve a stored fact."""
        if not self._available:
            return None
        try:
            from yesmem_tools import get_fact  # type: ignore

            return get_fact(project=self.project, key=key)
        except Exception as exc:
            logger.debug("YesMem recall failed: %s", exc)
            return None
