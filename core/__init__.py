"""
core — JARVIS Core Modules

This package contains the core functionality of JARVIS:
- Event engine and real-time context awareness
- Feature flags for safe rollout
- Awareness engine for correlated state
- Multi-person voice recognition
- Dynamic window management
- Enhanced persistent memory
- Task orchestration
- Interactive HUD

The KD upgrade names below are exported LAZILY (PEP 562). `import core` is on
the hot path of application startup, and eagerly importing the upgrade
modules would drag numpy, psutil and optional backends into every session
even though they are all disabled by default. Lazy export keeps startup
identical to the pre-upgrade package while `from core import AwarenessEngine`
still works exactly as before.
"""
from __future__ import annotations

import importlib

# name -> defining module
_LAZY_EXPORTS = {
    # Feature flags
    "is_enabled": "core.feature_flags",
    "set_flag": "core.feature_flags",
    "get_flag": "core.feature_flags",
    "all_flags": "core.feature_flags",
    "get_enabled_flags": "core.feature_flags",
    "validate_dependencies": "core.feature_flags",
    "override_flag": "core.feature_flags",
    "clear_overrides": "core.feature_flags",
    "any_kd_features_enabled": "core.feature_flags",
    # Event engine
    "Event": "core.event_engine",
    "EventBus": "core.event_engine",
    "get_event_bus": "core.event_engine",
    # Real-time context
    "RealtimeContext": "core.realtime_context",
    "get_realtime_context": "core.realtime_context",
    "realtime_context_enabled": "core.realtime_context",
    # Awareness engine
    "AwarenessEngine": "core.awareness_engine",
    "get_awareness_engine": "core.awareness_engine",
    "EventType": "core.awareness_engine",
    "publish_event": "core.awareness_engine",
    "subscribe_events": "core.awareness_engine",
    "unsubscribe_events": "core.awareness_engine",
    # Multi-person voice
    "MultiPersonVoiceProcessor": "core.multi_person_voice",
    "get_multi_person_voice": "core.multi_person_voice",
    "SpeakerProfile": "core.multi_person_voice",
    "DiarizationResult": "core.multi_person_voice",
    # Window manager
    "WindowManager": "core.window_manager",
    "get_window_manager": "core.window_manager",
    "WindowInfo": "core.window_manager",
    "MonitorInfo": "core.window_manager",
    "LayoutRule": "core.window_manager",
    "WindowState": "core.window_manager",
    # Persistent memory
    "PersistentMemoryEngine": "core.persistent_memory",
    "get_persistent_memory": "core.persistent_memory",
    "EnhancedMemoryEntry": "core.persistent_memory",
    "enhanced_store": "core.persistent_memory",
    "enhanced_recall": "core.persistent_memory",
    # Task orchestration
    "TaskOrchestrator": "core.task_orchestration",
    "get_task_orchestrator": "core.task_orchestration",
    "Task": "core.task_orchestration",
    "TaskStep": "core.task_orchestration",
    "TaskStatus": "core.task_orchestration",
    "TaskPriority": "core.task_orchestration",
    # Interactive HUD
    "InteractiveHUD": "core.interactive_hud",
    "get_interactive_hud": "core.interactive_hud",
    "WidgetConfig": "core.interactive_hud",
    "WidgetState": "core.interactive_hud",
    "WidgetType": "core.interactive_hud",
    "create_hud_overlay_widget": "core.interactive_hud",
    # Runtime adapter
    "KDRuntime": "core.kd_runtime",
    "get_kd_runtime": "core.kd_runtime",
}


def __getattr__(name: str):
    """Resolve a lazily exported name (PEP 562)."""
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module 'core' has no attribute {name!r}")
    module = importlib.import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value          # cache for subsequent lookups
    return value


def __dir__():
    return sorted(set(list(globals().keys()) + list(_LAZY_EXPORTS.keys())))


def get_available_modules() -> dict[str, bool]:
    """Report which KD upgrade modules can actually be imported.

    Each module is imported in isolation so one broken optional dependency
    only marks its own entry as unavailable.
    """
    modules = {
        "awareness_engine": "core.awareness_engine",
        "multi_person_voice": "core.multi_person_voice",
        "window_manager": "core.window_manager",
        "persistent_memory": "core.persistent_memory",
        "task_orchestration": "core.task_orchestration",
        "interactive_hud": "core.interactive_hud",
        "kd_runtime": "core.kd_runtime",
    }
    out: dict[str, bool] = {}
    for label, module_name in modules.items():
        try:
            importlib.import_module(module_name)
            out[label] = True
        except Exception:
            out[label] = False
    return out


def initialize_kd_upgrades(
    qt_parent=None,
    tool_runner=None,
    stt_provider=None,
) -> dict[str, bool]:
    """Start every enabled KD upgrade subsystem.

    Thin wrapper over core.kd_runtime.KDRuntime.start() so the historical
    entry point keeps working. Returns dict of subsystem -> started.
    """
    from core.kd_runtime import get_kd_runtime
    runtime = get_kd_runtime()
    runtime.start(tool_runner=tool_runner)
    return runtime.status().get("subsystems", {})


def shutdown_kd_upgrades() -> None:
    """Stop every started KD upgrade subsystem."""
    from core.kd_runtime import get_kd_runtime
    try:
        get_kd_runtime().stop()
    except Exception:
        pass


__all__ = sorted(_LAZY_EXPORTS.keys()) + [
    "get_available_modules",
    "initialize_kd_upgrades",
    "shutdown_kd_upgrades",
]

