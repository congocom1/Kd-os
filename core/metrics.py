"""
Observability & Metrics for JARVIS Codebase
==============================
Tracks key operations, error rates, and performance metrics.
Used by actions and plugins for observability.
"""

from __future__ import annotations
import time
import threading
from collections import defaultdict
from platform import python_version

# ── Global metrics counters ──────────────────────────────────────────────
_counters = defaultdict(int)
_timings = defaultdict(list)
_errors = defaultdict(int)
_start_time = time.time()
_lock = threading.Lock()

# ── Public API ───────────────────────────────────────────────────────────
class Metrics:
    """Singleton-like metrics class for the codebase."""
    
    @classmethod
    def increment(cls, key: str, amount: int = 1) -> None:
        """Increment a metrics counter."""
        with _lock:
            _counters[key] += amount
    
    @classmethod
    def record_timing(cls, key: str, duration: float) -> None:
        """Record a timing for an operation."""
        with _lock:
            _timings[key].append(duration)
    
    @classmethod
    def increment_errors(cls, key: str, amount: int = 1) -> None:
        """Increment error counter."""
        with _lock:
            _errors[key] += amount
    
    @classmethod
    def get_counters(cls) -> dict:
        """Return all metrics counters."""
        with _lock:
            return dict(_counters)
    
    @classmethod
    def get_timings(cls, key: str) -> dict:
        """Return timing statistics for a key."""
        with _lock:
            durations = _timings.get(key, [])
            if not durations:
                return {"count": 0, "min": 0, "max": 0, "avg": 0}
            return {
                "count": len(durations),
                "min": min(durations),
                "max": max(durations),
                "avg": sum(durations) / len(durations),
            }
    
    @classmethod
    def get_summary(cls) -> dict:
        """Return a full observability summary."""
        with _lock:
            uptime = time.time() - _start_time
            return {
                "uptime_seconds": round(uptime, 2),
                "total_operations": sum(_counters.values()),
                "total_errors": sum(_errors.values()),
                "operations": dict(_counters),
                "errors": dict(_errors),
                "python_version": python_version(),
            }

# Convenience functions for common patterns
def track_operation(operation_name: str):
    """Decorator to track function operations."""
    def decorator(func):
        from functools import wraps
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                Metrics.increment(f"{operation_name}.success")
                Metrics.record_timing(f"{operation_name}.time", time.time() - start)
                return result
            except Exception as e:
                Metrics.increment(f"{operation_name}.failure")
                Metrics.increment_errors(f"{operation_name}.error")
                Metrics.record_timing(f"{operation_name}.time", time.time() - start)
                raise
        return wrapper
    return decorator

# Singleton instance
metrics = Metrics()

# Aliases for convenience
increment = metrics.increment
record_timing = metrics.record_timing
increment_errors = metrics.increment_errors
get_counters = metrics.get_counters
get_summary = metrics.get_summary
