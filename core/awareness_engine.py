"""
core/awareness_engine.py — Real-time Awareness Engine (KD Upgrade).

Extends the existing event_engine + realtime_context with:
  • Typed event schemas for all subsystems
  • Automatic event correlation and pattern detection
  • Real-time metrics aggregation
  • Contextual awareness queries for agents/plugins
  • Zero-regression: purely additive, gated by REALTIME_AWARENESS flag

This module is purely additive — it subscribes to the event bus and provides
higher-level queries. It never writes back into main.py or existing systems.
"""

from __future__ import annotations

import logging
import time
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

from core.event_engine import get_event_bus, Event
from core.feature_flags import is_enabled


logger = logging.getLogger("jarvis.awareness")


# ── Event Type Constants (extend as subsystems are added) ─────────────────────

class EventType:
    """Standardized event type strings for type-safe subscriptions."""

    # System lifecycle
    SYSTEM_START = "system.start"
    SYSTEM_SHUTDOWN = "system.shutdown"
    SYSTEM_ERROR = "system.error"

    # Wake/sleep state
    WAKE_STATE = "wake.state"
    WAKE_DETECTED = "wake.detected"

    # Voice/speech
    VOICE_SPEAKING = "voice.speaking"
    VOICE_USER_SPEECH = "voice.user_speech"
    VOICE_TRANSCRIPT = "voice.transcript"
    VOICE_SPEAKER_CHANGED = "voice.speaker_changed"

    # HUD / UI
    HUD_TASK_MODE = "hud.task_mode"
    HUD_METRICS = "hud.metrics"
    HUD_ALERT = "hud.alert"

    # Window management
    WINDOW_FOCUS = "window.focus"
    WINDOW_LAYOUT = "window.layout"
    WINDOW_CREATED = "window.created"
    WINDOW_CLOSED = "window.closed"

    # Task orchestration
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_PROGRESS = "task.progress"

    # Memory
    MEMORY_STORED = "memory.stored"
    MEMORY_RECALLED = "memory.recalled"
    MEMORY_SEARCH = "memory.search"

    # Proactive
    PROACTIVE_SUGGESTION = "proactive.suggestion"
    PROACTIVE_ACTION = "proactive.action"

    # Visual grounding
    VISUAL_SCREEN_CHANGED = "visual.screen_changed"
    VISUAL_OBJECT_DETECTED = "visual.object_detected"
    VISUAL_TEXT_DETECTED = "visual.text_detected"

    # Metrics / health
    METRICS_SNAPSHOT = "metrics.snapshot"
    METRICS_CPU = "metrics.cpu"
    METRICS_MEMORY = "metrics.memory"
    METRICS_GPU = "metrics.gpu"
    METRICS_NETWORK = "metrics.network"


# ── Typed Event Payloads ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class WakeStatePayload:
    state: str  # "awake" | "asleep"
    reason: str
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class VoiceTranscriptPayload:
    text: str
    speaker_id: str | None = None
    confidence: float = 1.0
    language: str | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class TaskPayload:
    task_id: str
    name: str
    status: str  # "started" | "completed" | "failed" | "progress"
    progress: float | None = None  # 0.0 - 1.0
    metadata: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class WindowPayload:
    window_id: str
    title: str
    app_name: str
    bounds: dict  # x, y, width, height
    focused: bool
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class MetricsPayload:
    cpu_percent: float
    memory_percent: float
    gpu_percent: float | None = None
    network_mbps: float | None = None
    timestamp: float = field(default_factory=time.time)


# ── Awareness Engine ──────────────────────────────────────────────────────────

class AwarenessEngine:
    """
    High-level real-time awareness engine.

    Subscribes to the event bus and maintains correlated state views
    for easy querying by agents, plugins, and the HUD.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._started = False
        self._sub_tokens: list[int] = []

        # Rolling state by facet (latest value + timestamp)
        self._state: dict[str, tuple[Any, float]] = {}

        # Event correlation: recent events by type for pattern detection
        self._recent_events: dict[str, deque[Event]] = defaultdict(lambda: deque(maxlen=100))

        # Aggregated metrics (time-windowed)
        self._metrics_windows: dict[str, deque[tuple[float, float]]] = defaultdict(lambda: deque(maxlen=60))  # 60s windows

        # Pattern detectors (callbacks fired on pattern match)
        self._pattern_detectors: list[tuple[str, Callable[[list[Event]], None]]] = []

        # Speaker tracking for multi-person voice
        self._speaker_profiles: dict[str, dict] = {}
        self._current_speaker: str | None = None

    def start(self) -> None:
        """Start the awareness engine (subscribes to event bus)."""
        if self._started:
            return
        if not is_enabled("REALTIME_AWARENESS"):
            logger.info("Awareness engine not started: REALTIME_AWARENESS flag is off")
            return

        bus = get_event_bus()
        if not bus.running:
            bus.start()

        # Subscribe to all event types we care about
        self._sub_tokens = [
            bus.subscribe(self._on_event),  # All events
        ]

        self._started = True
        logger.info("Awareness engine started")

    def stop(self) -> None:
        """Stop the awareness engine."""
        if not self._started:
            return
        bus = get_event_bus()
        for token in self._sub_tokens:
            bus.unsubscribe(token)
        self._sub_tokens.clear()
        self._started = False
        logger.info("Awareness engine stopped")

    def _on_event(self, ev: Event) -> None:
        """Process incoming event: update state, correlate, detect patterns."""
        with self._lock:
            # Update rolling state
            self._state[ev.type] = (ev.payload, ev.ts)

            # Store for correlation
            self._recent_events[ev.type].append(ev)

            # Update metrics windows
            if ev.type.startswith("metrics."):
                if isinstance(ev.payload, dict):
                    for k, v in ev.payload.items():
                        if isinstance(v, (int, float)):
                            self._metrics_windows[f"metrics.{k}"].append((ev.ts, float(v)))

            # Speaker tracking
            if ev.type == EventType.VOICE_SPEAKER_CHANGED:
                self._current_speaker = ev.payload.get("speaker_id")
                if self._current_speaker and self._current_speaker not in self._speaker_profiles:
                    self._speaker_profiles[self._current_speaker] = {
                        "first_seen": ev.ts,
                        "last_seen": ev.ts,
                        "utterance_count": 0,
                    }
                if self._current_speaker:
                    self._speaker_profiles[self._current_speaker]["last_seen"] = ev.ts
                    self._speaker_profiles[self._current_speaker]["utterance_count"] += 1

            # Run pattern detectors
            self._check_patterns(ev)

    def _check_patterns(self, ev: Event) -> None:
        """Check registered patterns against recent events."""
        for pattern_type, callback in self._pattern_detectors:
            if pattern_type == ev.type or pattern_type == "*":
                try:
                    callback(list(self._recent_events[ev.type]))
                except Exception as e:
                    logger.warning(f"Pattern detector for {pattern_type} failed: {e}")

    def register_pattern(self, event_type: str, callback: Callable[[list[Event]], None]) -> int:
        """Register a pattern detector for an event type (or '*' for all).

        Returns a token that can be passed to unregister_pattern().
        """
        self._pattern_detectors.append((event_type, callback))
        return len(self._pattern_detectors) - 1

    def unregister_pattern(self, token: int) -> bool:
        """Remove a pattern detector by the token register_pattern returned."""
        try:
            self._pattern_detectors.pop(token)
            return True
        except (IndexError, TypeError):
            return False

    # ── Publishing ────────────────────────────────────────────────────────────

    def publish(self, event_type: str, payload: dict | None = None,
                source: str = "awareness") -> Event:
        """Publish an event on the shared bus.

        Subsystems call this instead of reaching into the bus object
        directly — the earlier `engine._awareness._event_bus` chain did not
        exist and silently swallowed every publish inside a bare except.
        """
        return get_event_bus().publish(event_type, payload, source)

    # ── State Queries ─────────────────────────────────────────────────────────

    def get_state(self, event_type: str, default=None) -> Any:
        """Get latest value for an event type."""
        with self._lock:
            entry = self._state.get(event_type)
            return entry[0] if entry else default

    def get_state_with_age(self, event_type: str) -> tuple[Any, float] | None:
        """Get latest value and its age in seconds."""
        with self._lock:
            entry = self._state.get(event_type)
            if entry:
                return entry[0], time.time() - entry[1]
            return None

    def get_all_state(self) -> dict[str, dict]:
        """Get snapshot of all tracked state with ages."""
        now = time.time()
        with self._lock:
            return {
                k: {"value": v[0], "age_s": round(now - v[1], 2)}
                for k, v in self._state.items()
            }

    def get_recent(self, event_type: str, limit: int = 10) -> list[Event]:
        """Get recent events of a type."""
        with self._lock:
            return list(self._recent_events[event_type])[-limit:]

    # ── Metrics Queries ───────────────────────────────────────────────────────

    def get_metric_avg(self, metric: str, window_sec: float = 60.0) -> float | None:
        """Get average of a metric over a time window."""
        now = time.time()
        cutoff = now - window_sec
        with self._lock:
            window = self._metrics_windows.get(metric)
            if not window:
                return None
            values = [v for ts, v in window if ts >= cutoff]
            return sum(values) / len(values) if values else None

    def get_metric_trend(self, metric: str, window_sec: float = 60.0) -> str | None:
        """Get trend direction: 'up', 'down', 'stable', or None."""
        now = time.time()
        cutoff = now - window_sec
        with self._lock:
            window = self._metrics_windows.get(metric)
            if not window:
                return None
            values = [v for ts, v in window if ts >= cutoff]
            if len(values) < 3:
                return "stable"
            # Simple linear trend
            n = len(values)
            x_avg = (n - 1) / 2
            y_avg = sum(values) / n
            num = sum((i - x_avg) * (v - y_avg) for i, v in enumerate(values))
            den = sum((i - x_avg) ** 2 for i in range(n))
            if den == 0:
                return "stable"
            slope = num / den
            if slope > 0.01:
                return "up"
            elif slope < -0.01:
                return "down"
            return "stable"

    # ── Speaker Tracking ──────────────────────────────────────────────────────

    def get_current_speaker(self) -> str | None:
        """Get the currently active speaker ID."""
        with self._lock:
            return self._current_speaker

    def get_speaker_profile(self, speaker_id: str) -> dict | None:
        """Get profile for a speaker."""
        with self._lock:
            return self._speaker_profiles.get(speaker_id)

    def get_all_speakers(self) -> list[dict]:
        """Get all known speaker profiles."""
        with self._lock:
            return [
                {"speaker_id": k, **v}
                for k, v in self._speaker_profiles.items()
            ]

    # ── High-Level Context Queries ────────────────────────────────────────────

    def is_awake(self) -> bool:
        """Check if assistant is awake."""
        state = self.get_state(EventType.WAKE_STATE)
        return state.get("state") == "awake" if isinstance(state, dict) else False

    def get_task_mode(self) -> str:
        """Get current HUD task mode."""
        state = self.get_state(EventType.HUD_TASK_MODE)
        return state.get("mode", "idle") if isinstance(state, dict) else "idle"

    def get_active_task(self) -> dict | None:
        """Get currently active task info."""
        state = self.get_state(EventType.TASK_STARTED)
        if isinstance(state, dict) and state.get("status") == "started":
            return state
        return None

    def get_window_context(self) -> dict | None:
        """Get current window focus context."""
        return self.get_state(EventType.WINDOW_FOCUS)

    def get_system_health(self) -> dict:
        """Get aggregated system health snapshot."""
        return {
            "cpu": self.get_metric_avg("metrics.cpu") or 0,
            "memory": self.get_metric_avg("metrics.memory") or 0,
            "gpu": self.get_metric_avg("metrics.gpu"),
            "network": self.get_metric_avg("metrics.network"),
            "cpu_trend": self.get_metric_trend("metrics.cpu"),
            "memory_trend": self.get_metric_trend("metrics.memory"),
            "awake": self.is_awake(),
            "task_mode": self.get_task_mode(),
            "speaker": self.get_current_speaker(),
            "timestamp": time.time(),
        }


# ── Singleton Instance ────────────────────────────────────────────────────────

_engine: AwarenessEngine | None = None


def get_awareness_engine() -> AwarenessEngine:
    """Get or create the singleton awareness engine."""
    global _engine
    if _engine is None:
        _engine = AwarenessEngine()
    return _engine


# ── Convenience Functions ─────────────────────────────────────────────────────

def publish_event(event_type: str, payload: dict | None = None, source: str = "awareness") -> Event:
    """Convenience: publish an event to the bus."""
    bus = get_event_bus()
    return bus.publish(event_type, payload, source)


def subscribe_events(callback: Callable[[Event], None], event_type: str | None = None) -> int:
    """Convenience: subscribe to events."""
    bus = get_event_bus()
    return bus.subscribe(callback, event_type)


def unsubscribe_events(token: int) -> None:
    """Convenience: unsubscribe from events."""
    bus = get_event_bus()
    bus.unsubscribe(token)