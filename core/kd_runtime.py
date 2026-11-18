"""
core/kd_runtime.py — Compatibility adapter for the KD upgrade subsystems.

This module is the single place that knows how the new subsystems fit
together. Everything else (main.py, actions, the HUD) talks to this adapter
instead of importing awareness_engine / persistent_memory / task_orchestration
directly, so:

  * a missing optional dependency degrades one subsystem, never the app;
  * every subsystem stays behind its own feature flag;
  * the adapter can be tested without a GUI, a microphone, or a network.

Nothing here changes existing behaviour: with every flag off (the default),
every call returns an "unavailable" answer instead of raising.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from core.feature_flags import is_enabled, all_flags

logger = logging.getLogger("jarvis.kd_runtime")


class KDRuntime:
    """Lazy, flag-gated access to the KD subsystems."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._started = False
        self._tool_runner: Callable[[str, dict], Any] | None = None
        self._awareness = None
        self._memory = None
        self._orchestrator = None
        self._window_manager = None
        self._voice = None
        self._hud = None

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def start(self, tool_runner: Callable[[str, dict], Any] | None = None) -> dict:
        """Start every enabled subsystem. Returns per-subsystem status.

        Each subsystem is independent: one failing never stops the others,
        and one flag never switches on an unrelated capability.
        """
        with self._lock:
            if self._started:
                return self.status()
            self._tool_runner = tool_runner
            status = {name: False for name in (
                "awareness", "memory", "orchestration", "windows", "voice", "hud")}

            if is_enabled("REALTIME_AWARENESS"):
                try:
                    from core.awareness_engine import get_awareness_engine
                    self._awareness = get_awareness_engine()
                    self._awareness.start()
                    status["awareness"] = bool(self._awareness._started)
                except Exception as e:
                    logger.warning("KD awareness engine unavailable: %s", e)

            if is_enabled("PERSISTENT_MEMORY"):
                try:
                    from core.persistent_memory import get_persistent_memory
                    self._memory = get_persistent_memory()
                    status["memory"] = self._memory is not None
                except Exception as e:
                    logger.warning("KD persistent memory unavailable: %s", e)

            if is_enabled("TASK_ORCHESTRATION"):
                try:
                    from core.task_orchestration import get_task_orchestrator
                    self._orchestrator = get_task_orchestrator(tool_runner)
                    status["orchestration"] = self._orchestrator is not None
                except Exception as e:
                    logger.warning("KD task orchestration unavailable: %s", e)

            if is_enabled("DYNAMIC_WINDOWS"):
                try:
                    from core.window_manager import get_window_manager
                    self._window_manager = get_window_manager()
                    if self._window_manager is not None:
                        self._window_manager.start()
                    status["windows"] = self._window_manager is not None
                except Exception as e:
                    logger.warning("KD window manager unavailable: %s", e)

            if is_enabled("MULTI_PERSON_VOICE"):
                try:
                    from core.multi_person_voice import get_multi_person_voice
                    self._voice = get_multi_person_voice()
                    status["voice"] = self._voice is not None
                except Exception as e:
                    logger.warning("KD multi-person voice unavailable: %s", e)

            if is_enabled("INTERACTIVE_HUD"):
                try:
                    from core.interactive_hud import get_interactive_hud
                    self._hud = get_interactive_hud(None, tool_runner)
                    status["hud"] = self._hud is not None
                except Exception as e:
                    logger.warning("KD interactive HUD unavailable: %s", e)

            self._started = True
            return status

    def stop(self) -> None:
        """Stop every started subsystem, ignoring individual failures."""
        with self._lock:
            for attr, method in (
                ("_hud", "shutdown"),
                ("_orchestrator", "shutdown"),
                ("_window_manager", "stop"),
                ("_memory", "shutdown"),
                ("_voice", "shutdown"),
                ("_awareness", "stop"),
            ):
                obj = getattr(self, attr, None)
                if obj is None:
                    continue
                try:
                    getattr(obj, method)()
                except Exception:
                    pass
                setattr(self, attr, None)
            self._started = False

    # ── Status ──────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Current status of every KD subsystem and feature flag."""
        flags = all_flags()
        return {
            "started": self._started,
            "flags": {name: flag.get() for name, flag in flags.items()},
            "effective": {name: is_enabled(name) for name in flags},
            "subsystems": {
                "awareness": self._awareness is not None,
                "memory": self._memory is not None,
                "orchestration": self._orchestrator is not None,
                "windows": self._window_manager is not None,
                "voice": self._voice is not None,
                "hud": self._hud is not None,
            },
            "timestamp": time.time(),
        }

    # ── Awareness ───────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """A single view of what the assistant knows right now."""
        out: dict[str, Any] = {"timestamp": time.time()}
        if self._awareness is not None:
            try:
                out["awareness"] = self._awareness.get_all_state()
                out["health"] = self._awareness.get_system_health()
            except Exception:
                out["awareness"] = {}
        if self._memory is not None:
            try:
                out["memory"] = self._memory.get_session_context()
            except Exception:
                out["memory"] = {}
        if self._orchestrator is not None:
            try:
                tasks = self._orchestrator.list_tasks(limit=5)
                out["tasks"] = [t.to_dict() for t in tasks]
            except Exception:
                out["tasks"] = []
        if self._window_manager is not None:
            try:
                active = self._window_manager.get_active_window()
                out["active_window"] = active.to_dict() if active else None
            except Exception:
                out["active_window"] = None
        if self._voice is not None:
            try:
                out["speakers"] = [p.get("speaker_id") for p in self._voice.list_profiles()]
            except Exception:
                out["speakers"] = []
        return out

    def publish(self, event_type: str, payload: dict | None = None) -> bool:
        """Publish an event onto the KD bus (no-op when awareness is off)."""
        if self._awareness is None:
            return False
        try:
            self._awareness.publish(event_type, payload, source="kd_runtime")
            return True
        except Exception:
            return False

    # ── Task orchestration ──────────────────────────────────────────────────

    def submit_task(self, goal: str, priority: str = "normal") -> dict:
        """Queue an autonomous task. Refuses when orchestration is off."""
        if self._orchestrator is None:
            return {"status": "unavailable",
                    "detail": "Task orchestration is disabled "
                              "(KD_AUTONOMOUS_ACTIONS_ENABLED / TASK_ORCHESTRATION)."}
        try:
            from core.task_orchestration import TaskPriority
            prio = TaskPriority[str(priority).upper()] if priority else TaskPriority.NORMAL
        except Exception:
            prio = None
        try:
            task = self._orchestrator.submit_task(goal, priority=prio) if prio \
                else self._orchestrator.submit_task(goal)
            return {"status": "queued", "task": task.to_dict()}
        except Exception as e:
            return {"status": "failed", "detail": str(e)}

    def task_status(self, task_id: str | None = None) -> dict:
        if self._orchestrator is None:
            return {"status": "unavailable"}
        try:
            if task_id:
                task = self._orchestrator.get_task_status(task_id)
                return {"status": "not_found" if task is None else "ok",
                        "task": task.to_dict() if task else None}
            tasks = self._orchestrator.list_tasks(limit=10)
            return {"status": "ok", "tasks": [t.to_dict() for t in tasks]}
        except Exception as e:
            return {"status": "failed", "detail": str(e)}

    # ── Memory ──────────────────────────────────────────────────────────────

    def recall(self, query: str, limit: int = 5) -> list[dict]:
        if self._memory is None:
            return []
        try:
            return self._memory.recall(query, limit)
        except Exception:
            return []

    def remember(self, category: str, key: str, value: str) -> dict:
        if self._memory is None:
            return {"status": "unavailable"}
        try:
            entry_id = self._memory.store(category, key, value)
            return {"status": "stored", "entry_id": entry_id}
        except Exception as e:
            return {"status": "failed", "detail": str(e)}

    # ── Windows ─────────────────────────────────────────────────────────────

    def list_windows(self) -> list[dict]:
        if self._window_manager is None:
            return []
        try:
            return [w.to_dict() for w in self._window_manager.enumerate_windows()]
        except Exception:
            return []

    def focus_window(self, window_id: str) -> dict:
        if self._window_manager is None:
            return {"status": "unavailable"}
        try:
            ok = self._window_manager.focus_window(window_id)
            return {"status": "done" if ok else "failed",
                    "window_id": window_id}
        except Exception as e:
            return {"status": "failed", "detail": str(e)}


_runtime: KDRuntime | None = None
_runtime_lock = threading.Lock()


def get_kd_runtime() -> KDRuntime:
    """Process-wide runtime adapter."""
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = KDRuntime()
        return _runtime
