"""Share a recent hardware snapshot between dashboard clients."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from time import monotonic, time

logger = logging.getLogger(__name__)


class TelemetryFeed:
    """On-demand sampler owned by one dashboard event loop.

    There is no idle sampler. Concurrent readers share one worker thread, and
    a disconnected reader cannot cancel or duplicate that worker's probe.
    """

    def __init__(self, collect: Callable[[], dict], interval: float):
        self._collect = collect
        self._interval = interval
        self._cached: dict | None = None
        self._refresh_at = 0.0
        self._pending: asyncio.Task[dict] | None = None

    async def snapshot(self) -> dict:
        if self._cached is not None and monotonic() < self._refresh_at:
            return self._cached
        if self._pending is None or self._pending.done():
            self._pending = asyncio.create_task(self._refresh())
        return await asyncio.shield(self._pending)

    async def _refresh(self) -> dict:
        try:
            data = await asyncio.to_thread(self._collect)
        except Exception as exc:
            # Never send exception text or probe stderr to the client.
            logger.warning("Telemetry collection failed (%s)", type(exc).__name__)
            data = {
                "schema_version": "1.0",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "unavailable",
                "process": {},
                "system": {},
                "gpu": {"status": "unavailable"},
            }
        self._cached = {**data, "last_updated": time()}
        self._refresh_at = monotonic() + self._interval
        return self._cached
