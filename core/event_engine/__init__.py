"""core/event_engine — in-process pub/sub event bus (KD Stage 2).

Additive infrastructure: nothing in the existing app is required to publish,
and nothing breaks when nobody does. Subsystems that exist later (real-time
context, proactive intelligence, live HUD telemetry) subscribe here instead of
reaching into each other.

Guarantees:
  • thread-safe publish/subscribe; callbacks run on a dispatcher thread, never
    on the publisher's thread (the audio callback stays cheap);
  • slow subscribers cannot block publishers (bounded per-subscriber queue,
    drop-oldest with a counter);
  • a bounded ring buffer of recent events for late joiners and tests;
  • zero cost when unused: the bus only runs when started explicitly, and
    main.py starts it behind the realtime-context feature flag.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger("jarvis.event_engine")

HISTORY_LEN = 500
SUB_QUEUE_LEN = 100


@dataclass(frozen=True)
class Event:
    """One thing that happened. `type` is a dotted string, e.g. 'hud.task_mode',
    'wake.awake', 'metrics.snapshot'. Payload stays small and JSON-safe."""
    type: str
    payload: dict = field(default_factory=dict)
    source: str = "app"
    ts: float = field(default_factory=time.time)


@dataclass
class _Sub:
    event_type: str | None          # None = all events
    callback: object
    queue: queue.Queue


class EventBus:
    """Cheap-publish, async-dispatch pub/sub with history."""

    def __init__(self, history_len: int = HISTORY_LEN):
        self._subs: dict[int, _Sub] = {}
        self._lock = threading.Lock()
        self._next_id = 0
        self._history: deque[Event] = deque(maxlen=history_len)
        self._running = False
        self._dispatcher: threading.Thread | None = None
        self.dropped = 0

    # ── lifecycle ─────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._dispatcher = threading.Thread(
            target=self._dispatch_loop, daemon=True, name="EventBusDispatch")
        self._dispatcher.start()

    def stop(self) -> None:
        self._running = False
        with self._lock:
            for sub in self._subs.values():
                try:
                    sub.queue.put_nowait(None)
                except Exception:
                    pass

    @property
    def running(self) -> bool:
        return self._running

    # ── pub/sub ───────────────────────────────────────────────────────────
    def subscribe(self, callback, event_type: str | None = None) -> int:
        """Subscribe to one event type (or all when None). Returns a token for
        unsubscribe(). The callback runs on the dispatcher thread — keep it
        short or hand off to your own worker."""
        with self._lock:
            self._next_id += 1
            token = self._next_id
            self._subs[token] = _Sub(event_type, callback,
                                     queue.Queue(maxsize=SUB_QUEUE_LEN))
        # Replay matching history so a late subscriber sees current state.
        for ev in list(self._history):
            if event_type is None or ev.type == event_type:
                self._offer(self._subs[token], ev)
        return token

    def unsubscribe(self, token: int) -> None:
        with self._lock:
            self._subs.pop(token, None)

    def _offer(self, sub: _Sub, ev: Event) -> None:
        try:
            sub.queue.put_nowait(ev)
        except queue.Full:
            try:
                sub.queue.get_nowait()      # drop oldest; subscriber is behind
                sub.queue.put_nowait(ev)
            except Exception:
                pass
            self.dropped += 1

    def publish(self, event_type: str, payload: dict | None = None,
                source: str = "app") -> Event:
        """Record an event and offer it to matching subscribers. Never blocks."""
        ev = Event(type=event_type, payload=payload or {}, source=source)
        self._history.append(ev)
        with self._lock:
            targets = [s for s in self._subs.values()
                       if s.event_type is None or s.event_type == event_type]
        for sub in targets:
            self._offer(sub, ev)
        return ev

    # ── dispatch ──────────────────────────────────────────────────────────
    def _dispatch_loop(self) -> None:
        while self._running:
            with self._lock:
                items = list(self._subs.items())
            did_work = False
            for token, sub in items:
                try:
                    while True:
                        ev = sub.queue.get_nowait()
                        if ev is None:
                            return
                        did_work = True
                        try:
                            sub.callback(ev)
                        except Exception as e:
                            logger.warning("event subscriber %s failed: %s",
                                           token, e)
                except queue.Empty:
                    pass
            if not did_work:
                time.sleep(0.01)

    def history(self, event_type: str | None = None,
                limit: int = 50) -> list[Event]:
        """Most recent events, optionally filtered by type."""
        items = [e for e in self._history
                 if event_type is None or e.type == event_type]
        return items[-limit:]


# Process-wide singleton; created on first use, started explicitly.
_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
