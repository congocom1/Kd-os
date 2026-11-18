"""
core/feature_flags.py — Central feature flag system for JARVIS/KD upgrades.

All new capabilities are gated behind feature flags to ensure zero-regression
rollout. Flags can be controlled via:
  1. Environment variables (KD_<FLAG>_ENABLED — the names fixed by the
     zero-regression protocol, e.g. KD_REALTIME_CONTEXT_ENABLED)
  2. config/kd_features.json (persisted user settings — a DEDICATED file, so
     enabling a capability never rewrites the secrets file config/api_keys.json)
  3. Runtime API (for testing/debugging)

Default: ALL NEW FEATURES OFF — existing behavior preserved exactly.

A flag whose `requires` are not satisfied is never "effective": the raw
request is remembered (so the owner sees what they asked for) but the
capability stays off until its dependencies are on. That keeps one flag from
ever silently switching on an unrelated subsystem.
"""

from __future__ import annotations

import os
import json
import threading
from pathlib import Path
from typing import Callable
from dataclasses import dataclass, field


def _base_dir() -> Path:
    if getattr(__import__("sys"), "frozen", False):
        return Path(__import__("sys").executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _base_dir()
# Deliberately NOT config/api_keys.json: that file holds secrets and is
# written by the installer. Flags live in their own file so a flag flip can
# never damage or reorder the credentials file.
CONFIG_FILE = BASE_DIR / "config" / "kd_features.json"


@dataclass
class FeatureFlag:
    """A single feature flag with metadata."""
    name: str
    description: str
    default: bool = False
    env_var: str = ""
    config_key: str = ""
    requires: list[str] = field(default_factory=list)
    experimental: bool = False
    _value: bool | None = field(default=None, init=False, repr=False)
    _callbacks: list[Callable[[bool], None]] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self):
        if not self.env_var:
            self.env_var = f"KD_{self.name.upper()}_ENABLED"
        if not self.config_key:
            self.config_key = f"feature_{self.name.lower()}"

    def get(self) -> bool:
        """Get the effective value (env > config > default)."""
        if self._value is not None:
            return self._value

        # 1. Environment variable (highest priority)
        env = os.environ.get(self.env_var, "").strip().lower()
        if env in ("1", "true", "yes", "on"):
            return True
        if env in ("0", "false", "no", "off"):
            return False

        # 2. Config file
        try:
            if CONFIG_FILE.exists():
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                val = data.get(self.config_key)
                if isinstance(val, bool):
                    return val
        except Exception:
            pass

        # 3. Default
        return self.default

    def set(self, value: bool, persist: bool = True) -> None:
        """Set the flag value, optionally persisting to config."""
        old = self.get()
        self._value = value
        if persist and value != old:
            self._persist_to_config(value)
        if value != old:
            for cb in self._callbacks:
                try:
                    cb(value)
                except Exception:
                    pass

    def _persist_to_config(self, value: bool) -> None:
        """Persist to config/kd_features.json (never the secrets file)."""
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if CONFIG_FILE.exists():
                try:
                    data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                    if not isinstance(data, dict):
                        data = {}
                except Exception:
                    data = {}
            data[self.config_key] = value
            # Atomic write so an interrupted save cannot leave a truncated file.
            tmp = CONFIG_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, CONFIG_FILE)
        except Exception:
            pass

    def on_change(self, callback: Callable[[bool], None]) -> None:
        """Register a callback for value changes."""
        self._callbacks.append(callback)

    def is_available(self, all_flags: dict[str, "FeatureFlag"]) -> bool:
        """Check if all required flags are enabled."""
        for req in self.requires:
            if not all_flags[req].get():
                return False
        return True


# ── Feature Flag Registry ─────────────────────────────────────────────────────

_FLAGS: dict[str, FeatureFlag] = {}
_LOCK = threading.Lock()


def register_flag(flag: FeatureFlag) -> FeatureFlag:
    """Register a feature flag. Returns the flag for chaining."""
    with _LOCK:
        _FLAGS[flag.name] = flag
    return flag


def get_flag(name: str) -> FeatureFlag | None:
    """Get a feature flag by name."""
    with _LOCK:
        return _FLAGS.get(name)


def _dependencies_satisfied(name: str, flags: dict[str, FeatureFlag],
                            seen: set[str] | None = None) -> bool:
    """Check a flag's dependency chain, transitively.

    The check is transitive on purpose: TASK_ORCHESTRATION requires
    PERSISTENT_MEMORY, which itself requires REALTIME_AWARENESS. Looking only
    one level deep would report TASK_ORCHESTRATION as enabled while
    PERSISTENT_MEMORY — the thing it actually needs — was still off.
    """
    seen = seen if seen is not None else set()
    flag = flags.get(name)
    if flag is None:
        return False
    if name in seen:
        # Dependency cycle: stop recursing rather than loop forever.
        return True
    seen.add(name)
    for req in flag.requires:
        other = flags.get(req)
        if other is None or not other.get():
            return False
        if not _dependencies_satisfied(req, flags, seen):
            return False
    return True


def is_enabled(name: str) -> bool:
    """Check if a feature flag is enabled AND its dependencies are satisfied.

    A capability whose dependency is off stays off, whatever the owner asked
    for directly: switching on the HUD without the awareness engine it reads
    from would produce an empty panel, not a working feature.
    """
    flag = get_flag(name)
    if not flag:
        return False
    if not flag.get():
        return False
    return _dependencies_satisfied(name, all_flags())


def is_requested(name: str) -> bool:
    """True when the owner asked for the flag, ignoring dependencies."""
    flag = get_flag(name)
    return bool(flag and flag.get())


def set_flag(name: str, value: bool, persist: bool = True) -> bool:
    """Set a feature flag value. Returns True if flag exists."""
    flag = get_flag(name)
    if flag:
        flag.set(value, persist)
        return True
    return False


def all_flags() -> dict[str, FeatureFlag]:
    """Get all registered flags (copy)."""
    with _LOCK:
        return dict(_FLAGS)


def get_enabled_flags() -> list[str]:
    """Get list of enabled flag names."""
    return [name for name, flag in all_flags().items() if flag.get()]


def validate_dependencies() -> list[str]:
    """Check for unsatisfied dependencies. Returns list of error messages."""
    errors = []
    flags = all_flags()
    for name, flag in flags.items():
        if flag.get() and not flag.is_available(flags):
            for req in flag.requires:
                if not flags[req].get():
                    errors.append(f"{name} requires {req} to be enabled")
    return errors


# ── Core Feature Flags (register on import) ───────────────────────────────────

# Real-time Awareness Engine
# NOTE: the env var names below are the ones fixed by
# docs/architecture/KD_ZERO_REGRESSION_PROTOCOL.md §5. They are declared
# explicitly rather than derived, so the protocol's names always work.
register_flag(FeatureFlag(
    name="REALTIME_AWARENESS",
    description="Real-time context awareness engine (event bus + rolling state)",
    default=False,
    env_var="KD_REALTIME_CONTEXT_ENABLED",
    experimental=False,
))

# Multi-person Voice Recognition
register_flag(FeatureFlag(
    name="MULTI_PERSON_VOICE",
    description="Speaker diarization and multi-person voice recognition",
    default=False,
    env_var="KD_SPEAKER_IDENTITY_ENABLED",
    experimental=True,
    requires=["REALTIME_AWARENESS"],
))

# Dynamic Window Management
register_flag(FeatureFlag(
    name="DYNAMIC_WINDOWS",
    description="Dynamic window management and layout engine",
    default=False,
    env_var="KD_DYNAMIC_WINDOWS_ENABLED",
    experimental=False,
    requires=["REALTIME_AWARENESS"],
))

# Persistent Memory Enhancements
register_flag(FeatureFlag(
    name="PERSISTENT_MEMORY",
    description="Enhanced persistent memory with vector storage and semantic search",
    default=False,
    env_var="KD_PERSISTENT_MEMORY_ENABLED",
    experimental=False,
    requires=["REALTIME_AWARENESS"],
))

# Autonomous Task Orchestration
register_flag(FeatureFlag(
    name="TASK_ORCHESTRATION",
    description="Autonomous task planning and orchestration engine",
    default=False,
    env_var="KD_AUTONOMOUS_ACTIONS_ENABLED",
    experimental=True,
    requires=["REALTIME_AWARENESS", "PERSISTENT_MEMORY"],
))

# Interactive HUD Enhancements
register_flag(FeatureFlag(
    name="INTERACTIVE_HUD",
    description="Enhanced interactive HUD with real-time telemetry",
    default=False,
    env_var="KD_HOLOGRAPHIC_HUD_ENABLED",
    experimental=False,
    requires=["REALTIME_AWARENESS"],
))

# Proactive Intelligence (requires task orchestration)
register_flag(FeatureFlag(
    name="PROACTIVE_INTELLIGENCE",
    description="Proactive suggestions and autonomous actions",
    default=False,
    env_var="KD_PROACTIVE_INTELLIGENCE_ENABLED",
    experimental=True,
    requires=["TASK_ORCHESTRATION", "PERSISTENT_MEMORY"],
))

# Cross-session Continuity
register_flag(FeatureFlag(
    name="CROSS_SESSION_CONTINUITY",
    description="Maintain context and state across restarts/sessions",
    default=False,
    experimental=False,
    requires=["PERSISTENT_MEMORY"],
))

# Visual Grounding (screen understanding)
register_flag(FeatureFlag(
    name="VISUAL_GROUNDING",
    description="Screen content understanding and visual context awareness",
    default=False,
    experimental=True,
    requires=["REALTIME_AWARENESS"],
))

# Plugin Sandbox (isolated plugin execution)
register_flag(FeatureFlag(
    name="PLUGIN_SANDBOX",
    description="Sandboxed plugin execution with resource limits",
    default=False,
    experimental=True,
))


# ── Convenience: Check if any KD features are enabled ─────────────────────────

def any_kd_features_enabled() -> bool:
    """True if any KD upgrade feature is enabled."""
    return any(is_enabled(name) for name in [
        "REALTIME_AWARENESS", "MULTI_PERSON_VOICE", "DYNAMIC_WINDOWS",
        "PERSISTENT_MEMORY", "TASK_ORCHESTRATION", "INTERACTIVE_HUD",
        "PROACTIVE_INTELLIGENCE", "CROSS_SESSION_CONTINUITY",
        "VISUAL_GROUNDING", "PLUGIN_SANDBOX",
    ])


# ── Runtime flag override (for testing) ──────────────────────────────────────

_override: dict[str, bool] = {}


def override_flag(name: str, value: bool) -> None:
    """Temporarily override a flag value (testing only)."""
    _override[name] = value
    flag = get_flag(name)
    if flag:
        flag._value = value


def clear_overrides() -> None:
    """Clear all test overrides."""
    _override.clear()
    for flag in all_flags().values():
        flag._value = None