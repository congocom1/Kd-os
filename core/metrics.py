"""Lightweight process-local counters and timing statistics."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import wraps
from platform import python_version
import threading
import time


@dataclass(slots=True)
class _Timing:
    count: int
    minimum: float
    maximum: float
    total: float


_counters: dict[str, int] = defaultdict(int)
_timings: dict[str, _Timing] = {}
_errors: dict[str, int] = defaultdict(int)
_start_time = time.monotonic()
_lock = threading.Lock()


class Metrics:
    """Thread-safe lifetime statistics, with constant storage per metric."""

    @classmethod
    def increment(cls, key: str, amount: int = 1) -> None:
        with _lock:
            _counters[key] += amount

    @classmethod
    def record_timing(cls, key: str, duration: float) -> None:
        with _lock:
            timing = _timings.get(key)
            if timing is None:
                _timings[key] = _Timing(1, duration, duration, duration)
            else:
                timing.count += 1
                timing.minimum = min(timing.minimum, duration)
                timing.maximum = max(timing.maximum, duration)
                timing.total += duration

    @classmethod
    def increment_errors(cls, key: str, amount: int = 1) -> None:
        with _lock:
            _errors[key] += amount

    @classmethod
    def get_counters(cls) -> dict:
        with _lock:
            return dict(_counters)

    @classmethod
    def get_timings(cls, key: str) -> dict:
        with _lock:
            timing = _timings.get(key)
            if timing is None:
                return {"count": 0, "min": 0, "max": 0, "avg": 0}
            return {
                "count": timing.count,
                "min": timing.minimum,
                "max": timing.maximum,
                "avg": timing.total / timing.count,
            }

    @classmethod
    def get_summary(cls) -> dict:
        with _lock:
            return {
                "uptime_seconds": round(time.monotonic() - _start_time, 2),
                "total_operations": sum(_counters.values()),
                "total_errors": sum(_errors.values()),
                "operations": dict(_counters),
                "errors": dict(_errors),
                "python_version": python_version(),
            }


def track_operation(operation_name: str):
    """Record the timing and outcome of a synchronous operation."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
            except Exception:
                Metrics.increment(f"{operation_name}.failure")
                Metrics.increment_errors(f"{operation_name}.error")
                raise
            else:
                Metrics.increment(f"{operation_name}.success")
                return result
            finally:
                Metrics.record_timing(f"{operation_name}.time", time.perf_counter() - start)
        return wrapper
    return decorator


metrics = Metrics()
increment = metrics.increment
record_timing = metrics.record_timing
increment_errors = metrics.increment_errors
get_counters = metrics.get_counters
get_summary = metrics.get_summary
