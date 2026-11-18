"""In-process workflow scheduler; registrations and history are NOT durable.

Dispatchers receive ``(action, args)``. Cron uses local wall time: nonexistent
DST times are skipped and ambiguous times run once per distinct UTC instant.
``coalesce`` executes one overdue occurrence; ``skip`` drops occurrences older
than ``misfire_grace_seconds``. History and in-flight dedupe are memory-only.
"""
from __future__ import annotations

import copy
import logging
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Callable
from zoneinfo import ZoneInfo

try:
    from croniter import croniter
    _CRONITER_AVAILABLE = True
except ImportError:
    croniter = None
    _CRONITER_AVAILABLE = False

UTC = dt_timezone.utc
log = logging.getLogger(__name__)


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("scheduler clock must return a timezone-aware datetime")
    return value


def _make_croniter(expr: str, base: datetime):
    if not _CRONITER_AVAILABLE or croniter is None:
        raise RuntimeError("croniter is required to schedule cron jobs")
    return croniter(expr, base)


def _next_run_time(expr: str, base: datetime) -> datetime:
    """Return the next real instant, using explicit datetime croniter output.

    Generate wall-clock candidates then round-trip through UTC to reject gaps.
    Rewind across a forthcoming backward transition to include its second fold.
    Compare instants in UTC (datetime's same-zone comparisons ignore fold).
    """
    _aware(base)
    zone = base.tzinfo
    wall = base.replace(tzinfo=None)
    rewind = max(timedelta(0), base.utcoffset() -
                 (base + timedelta(days=1)).utcoffset())
    iterator = _make_croniter(expr, wall - rewind)
    candidates = []
    while True:
        candidate = iterator.get_next(datetime)
        for fold in (0, 1):
            local = candidate.replace(tzinfo=zone, fold=fold)
            instant = local.astimezone(UTC)
            if (instant > base.astimezone(UTC) and
                    instant.astimezone(zone).replace(tzinfo=None) == candidate):
                candidates.append(local)
        if candidate > wall and candidates:
            return min(candidates, key=lambda value: value.astimezone(UTC))


@dataclass
class ScheduledJob:
    job_id: str
    cron: str
    timezone: str = "UTC"
    action: str = ""
    args: dict = field(default_factory=dict)
    enabled: bool = True
    missed_policy: str = "coalesce"
    next_run: datetime | None = None
    last_run: datetime | None = None


@dataclass
class JobRunRecord:
    job_id: str
    scheduled_for: datetime
    started_at: datetime
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    finished_at: datetime | None = None
    status: str = "running"
    result: object = None
    error: str | None = None


class KDWorkflowScheduler:
    def __init__(self, dispatcher: Callable | None = None, *,
                 clock: Callable[[], datetime] | None = None,
                 poll_interval: float = 1.0, history_limit: int = 100,
                 misfire_grace_seconds: float = 60.0):
        if poll_interval <= 0 or history_limit < 1 or misfire_grace_seconds < 0:
            raise ValueError("invalid scheduler limits")
        self._dispatcher = dispatcher
        self._clock = clock or (lambda: datetime.now(UTC))
        self._poll_interval = poll_interval
        self._grace = misfire_grace_seconds
        self._jobs: dict[str, ScheduledJob] = {}
        self._history: deque[JobRunRecord] = deque(maxlen=history_limit)
        self._in_flight: set[str] = set()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def register(self, job_id: str, cron: str, timezone: str = "UTC",
                 action: str = "", args: dict | None = None, *,
                 enabled: bool = True, missed_policy: str = "coalesce") -> ScheduledJob:
        if not job_id or missed_policy not in {"coalesce", "skip"}:
            raise ValueError("job_id and a coalesce/skip missed_policy are required")
        zone = ZoneInfo(timezone)
        next_run = _next_run_time(cron, _aware(self._clock()).astimezone(zone))
        job = ScheduledJob(job_id, cron, timezone, action, copy.deepcopy(args or {}),
                           enabled, missed_policy, next_run)
        with self._lock:
            if job_id in self._jobs or job_id in self._in_flight:
                raise ValueError(f"job already registered or running: {job_id}")
            self._jobs[job_id] = job
            return copy.deepcopy(job)

    def unregister(self, job_id: str) -> bool:
        with self._lock:
            return self._jobs.pop(job_id, None) is not None

    def list_jobs(self) -> list[ScheduledJob]:
        with self._lock:
            return copy.deepcopy(list(self._jobs.values()))

    def get_job(self, job_id: str) -> ScheduledJob | None:
        with self._lock:
            return copy.deepcopy(self._jobs.get(job_id))

    def get_history(self, job_id: str | None = None, limit: int | None = None) -> list[JobRunRecord]:
        if limit is not None and limit < 0:
            raise ValueError("limit must be nonnegative")
        with self._lock:
            records = [r for r in self._history if job_id is None or r.job_id == job_id]
            return copy.deepcopy(records if limit is None else records[-limit:] if limit else [])

    def run_pending(self, now: datetime | None = None) -> list[JobRunRecord]:
        now = _aware(now if now is not None else self._clock()).astimezone(UTC)
        due = []
        with self._lock:
            for job in self._jobs.values():
                if (not job.enabled or job.next_run is None or
                        job.next_run.astimezone(UTC) > now or job.job_id in self._in_flight):
                    continue
                # Snapshot the due occurrence BEFORE advancing the schedule.
                snapshot = copy.deepcopy(job)
                next_run = _next_run_time(job.cron, now.astimezone(ZoneInfo(job.timezone)))
                job.next_run = next_run
                record = JobRunRecord(job.job_id, snapshot.next_run, now)
                if (job.missed_policy == "skip" and
                        (now - snapshot.next_run.astimezone(UTC)).total_seconds() > self._grace):
                    record.status = "skipped"
                    record.finished_at = now
                    self._history.append(record)
                    continue
                self._in_flight.add(job.job_id)
                due.append((snapshot, record))
        completed = []
        attempted = set()
        try:
            for job, record in due:
                # stop() from a dispatcher cancels the remaining claimed batch.
                if self._stop_event.is_set():
                    break
                attempted.add(job.job_id)
                try:
                    if self._dispatcher is None:
                        raise RuntimeError("no scheduler dispatcher configured")
                    record.result = self._dispatcher(job.action, job.args)
                    record.status = "success"
                except Exception as exc:
                    record.status = "failed"
                    record.error = str(exc)
                finally:
                    record.finished_at = _aware(self._clock())
                    with self._lock:
                        current = self._jobs.get(job.job_id)
                        if current is not None:
                            current.last_run = record.started_at
                        self._history.append(record)
                completed.append(copy.deepcopy(record))
        finally:
            with self._lock:
                for job, _ in due:
                    # A stop must not silently consume work never dispatched.
                    if job.job_id not in attempted and job.job_id in self._jobs:
                        self._jobs[job.job_id].next_run = job.next_run
                    self._in_flight.discard(job.job_id)
        return completed

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_pending()
            except Exception:
                log.exception("scheduler polling failed")
            self._stop_event.wait(self._poll_interval)

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._loop, name="kd-scheduler", daemon=True)
            self._thread.start()

    def stop(self, timeout: float | None = 5.0) -> bool:
        """Signal shutdown; never self-join or hold the lock while joining.

        Running dispatches cannot be forcibly cancelled. False means the loop
        is still alive; start() will not create a second loop in that case.
        """
        with self._lock:
            self._stop_event.set()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        return thread is None or not thread.is_alive()


_default_scheduler: KDWorkflowScheduler | None = None
_default_lock = threading.Lock()


def get_default_scheduler() -> KDWorkflowScheduler:
    global _default_scheduler
    with _default_lock:
        if _default_scheduler is None:
            _default_scheduler = KDWorkflowScheduler()
        return _default_scheduler
