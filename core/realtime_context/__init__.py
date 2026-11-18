"""core/realtime_context — rolling live picture of the assistant's state
(KD Stage 2).

Subscribes to the event bus and keeps the latest value of each state facet:
task mode, wake state, speaking/listening, last user speech, system metrics.
Later stages (proactive intelligence, HUD telemetry, agent orchestration)
query this instead of reaching into main.py internals.

Purely additive: it reads events; it never writes back into the app.
"""
from __future__ import annotations

import threading
import time

from core.event_engine import get_event_bus

# Facets tracked, with the event types that update them.
_FACETS = {
    "task_mode": "hud.task_mode",
    "wake_state": "wake.state",
    "speaking": "voice.speaking",
    "user_speech": "voice.user_speech",
    "metrics": "metrics.snapshot",
}


class RealtimeContext:
    """Latest-known state, fed by the event bus. Thread-safe reads."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state: dict[str, dict] = {}
        self._sub_token: int | None = None

    def start(self) -> None:
        """Subscribe to the bus and begin tracking. Idempotent."""
        if self._sub_token is not None:
            return
        bus = get_event_bus()
        if not bus.running:
            bus.start()
        self._sub_token = bus.subscribe(self._on_event)

    def stop(self) -> None:
        if self._sub_token is not None:
            get_event_bus().unsubscribe(self._sub_token)
            self._sub_token = None

    def _on_event(self, ev) -> None:
        for facet, etype in _FACETS.items():
            if ev.type == etype:
                with self._lock:
                    self._state[facet] = {"value": ev.payload, "ts": ev.ts}
                return

    def get(self, facet: str, default=None):
        """Latest value of a facet ('task_mode', 'wake_state', …) or default."""
        with self._lock:
            entry = self._state.get(facet)
        return entry["value"] if entry else default

    def snapshot(self) -> dict:
        """All facets with ages, for dashboards/agents."""
        now = time.time()
        with self._lock:
            return {k: {"value": v["value"], "age_s": round(now - v["ts"], 1)}
                    for k, v in self._state.items()}


_ctx: RealtimeContext | None = None


def get_realtime_context() -> RealtimeContext:
    global _ctx
    if _ctx is None:
        _ctx = RealtimeContext()
    return _ctx


# ── Feature flag ─────────────────────────────────────────────────────────────

def realtime_context_enabled() -> bool:
    """KD_REALTIME_CONTEXT_ENABLED env wins; else the feature flag; default off.

    Reads through core.feature_flags.is_enabled so the flag set in
    config/kd_features.json (feature_realtime_awareness) is honoured — not
    only a key buried in config/api_keys.json.
    """
    import os
    env = os.environ.get("KD_REALTIME_CONTEXT_ENABLED", "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    if env in ("0", "false", "no", "off"):
        return False
    try:
        from core.feature_flags import is_enabled
        return bool(is_enabled("REALTIME_AWARENESS"))
    except Exception:
        return False
