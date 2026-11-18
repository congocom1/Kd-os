"""Focused scheduler contracts, using controlled clocks and real zoneinfo DST."""
from datetime import datetime, timedelta, timezone
import threading
from zoneinfo import ZoneInfo

import pytest

from core import scheduler as module
from core.scheduler import KDWorkflowScheduler, ScheduledJob, JobRunRecord

UTC = timezone.utc


@pytest.fixture
def clock():
    class Clock:
        now = datetime(2025, 1, 1, tzinfo=UTC)

        def __call__(self):
            return self.now
    return Clock()


@pytest.fixture(autouse=True)
def require_cron(request):
    if request.node.name != "test_missing_croniter_fails_closed":
        pytest.importorskip("croniter")


def test_missing_croniter_fails_closed(monkeypatch, clock):
    monkeypatch.setattr(module, "_CRONITER_AVAILABLE", False)
    scheduler = KDWorkflowScheduler(clock=clock)
    with pytest.raises(RuntimeError, match="croniter"):
        scheduler.register("job", "0 8 * * *")
    assert scheduler.list_jobs() == []


def test_api_snapshot_coalesce_and_dedupe(clock):
    calls = []
    scheduler = KDWorkflowScheduler(lambda action, args: calls.append((action, args)), clock=clock)
    job = scheduler.register("job", "* * * * *", action="brief", args={"topic": ["news"]})
    assert isinstance(job, ScheduledJob)
    job.args["topic"].append("mutated")
    due = job.next_run
    clock.now += timedelta(hours=4)
    records = scheduler.run_pending()
    assert len(records) == 1 and isinstance(records[0], JobRunRecord)
    assert records[0].scheduled_for == due
    assert records[0].started_at == clock.now
    assert records[0].status == "success"
    assert calls == [("brief", {"topic": ["news"]})]
    assert scheduler.get_job("job").next_run > clock.now
    assert scheduler.run_pending() == []
    with pytest.raises(ValueError, match="already"):
        scheduler.register("job", "* * * * *")
    assert scheduler.unregister("job")
    assert not scheduler.unregister("job")


def test_skip_and_bounded_history(clock):
    calls = []
    scheduler = KDWorkflowScheduler(lambda *args: calls.append(args), clock=clock,
                                    history_limit=2, misfire_grace_seconds=2)
    scheduler.register("job", "* * * * *", missed_policy="skip")
    clock.now += timedelta(minutes=5)
    assert scheduler.run_pending() == []
    assert scheduler.get_history()[0].status == "skipped"
    for _ in range(3):
        clock.now += timedelta(minutes=1)
        scheduler.run_pending()
    assert len(calls) == 3
    assert len(scheduler.get_history()) == 2
    assert scheduler.get_history(limit=0) == []
    assert scheduler.get_history("missing") == []
    assert len(scheduler.get_history(limit=1)) == 1


def test_errors_do_not_block_other_jobs(clock):
    def dispatch(action, args):
        if action == "bad":
            raise ValueError("broken")
        return "ok"
    scheduler = KDWorkflowScheduler(dispatch, clock=clock)
    scheduler.register("bad", "* * * * *", action="bad")
    scheduler.register("good", "* * * * *", action="good")
    clock.now += timedelta(minutes=1)
    records = scheduler.run_pending()
    assert [r.status for r in records] == ["failed", "success"]
    assert records[0].error == "broken"
    assert records[1].result == "ok"


def test_dispatch_outside_lock_and_concurrent_dedupe(clock):
    entered, release, inspected = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def dispatch(*args):
        calls.append(args)
        entered.set()
        assert release.wait(3)

    scheduler = KDWorkflowScheduler(dispatch, clock=clock)
    scheduler.register("job", "* * * * *")
    clock.now += timedelta(minutes=1)
    worker = threading.Thread(target=scheduler.run_pending)
    worker.start()
    try:
        assert entered.wait(2)
        clock.now += timedelta(minutes=1)

        def inspect():
            scheduler.list_jobs()
            assert scheduler.run_pending() == []
            inspected.set()

        reader = threading.Thread(target=inspect)
        reader.start()
        assert inspected.wait(2), "dispatcher holds scheduler lock"
        reader.join(2)
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert len(calls) == 1


def test_stop_timeout_prevents_second_loop(clock):
    entered, release = threading.Event(), threading.Event()

    def dispatch(*args):
        entered.set()
        release.wait(3)

    scheduler = KDWorkflowScheduler(dispatch, clock=clock, poll_interval=.01)
    scheduler.register("job", "* * * * *")
    clock.now += timedelta(minutes=1)
    scheduler.start()
    try:
        assert entered.wait(2)
        original = scheduler._thread
        assert scheduler.stop(timeout=.01) is False
        scheduler.start()
        assert scheduler._thread is original
    finally:
        release.set()
        assert scheduler.stop(timeout=3)
    scheduler.start()
    assert scheduler._thread is not original
    assert scheduler.stop()


def test_dispatch_can_stop_own_loop(clock):
    stopped = threading.Event()
    calls = []

    def dispatch(action, args):
        calls.append(action)
        scheduler.stop()
        stopped.set()

    scheduler = KDWorkflowScheduler(dispatch, clock=clock)
    scheduler.register("one", "* * * * *", action="one")
    scheduler.register("two", "* * * * *", action="two")
    clock.now += timedelta(minutes=1)
    scheduler.start()
    assert stopped.wait(2)
    assert scheduler.stop()
    assert calls == ["one"]
    assert not scheduler._in_flight
    assert scheduler.get_job("two").next_run == clock.now


@pytest.mark.parametrize("zone,expr,base,expected", [
    ("America/New_York", "30 2 * * *", "2025-03-08T07:30:00+00:00", "2025-03-10T06:30:00+00:00"),
    ("America/New_York", "30 1 * * *", "2025-11-02T05:30:00+00:00", "2025-11-02T06:30:00+00:00"),
    ("America/New_York", "30 1 * * *", "2025-11-02T06:30:00+00:00", "2025-11-03T06:30:00+00:00"),
    ("Europe/London", "30 1 * * *", "2025-03-29T01:30:00+00:00", "2025-03-31T00:30:00+00:00"),
    ("Asia/Kolkata", "0 8 * * *", "2025-01-01T00:00:00+00:00", "2025-01-01T02:30:00+00:00"),
])
def test_cron_zoneinfo_dst(zone, expr, base, expected):
    result = module._next_run_time(expr, datetime.fromisoformat(base).astimezone(ZoneInfo(zone)))
    assert result.astimezone(UTC) == datetime.fromisoformat(expected)
    assert isinstance(result.tzinfo, ZoneInfo)


def test_dst_fold_due_compared_as_instants(clock):
    clock.now = datetime(2025, 11, 2, 5, 30, tzinfo=UTC)
    scheduler = KDWorkflowScheduler(lambda *args: None, clock=clock)
    scheduler.register("job", "30 1 * * *", timezone="America/New_York")
    clock.now += timedelta(minutes=15)
    assert scheduler.run_pending() == []
    clock.now += timedelta(minutes=45)
    record, = scheduler.run_pending()
    assert record.scheduled_for.fold == 1
    assert scheduler.run_pending() == []


def test_validation_and_default(clock):
    assert module.get_default_scheduler() is module.get_default_scheduler()
    scheduler = KDWorkflowScheduler(clock=clock)
    with pytest.raises(ValueError):
        scheduler.register("bad", "not cron")
    with pytest.raises(ValueError):
        scheduler.register("bad", "* * * * *", missed_policy="replay")
    with pytest.raises(KeyError):
        scheduler.register("bad", "* * * * *", timezone="No/SuchZone")
    with pytest.raises(ValueError, match="aware"):
        scheduler.run_pending(datetime(2025, 1, 1))
    assert scheduler.list_jobs() == []
