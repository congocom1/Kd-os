"""Dashboard clients share work without sharing their authorization state."""

import asyncio
import threading

import pytest

from dashboard import telemetry_feed
from dashboard.telemetry_feed import TelemetryFeed


def test_concurrent_and_cancelled_readers_share_one_probe():
    async def run():
        started = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        calls = 0
        def collect():
            nonlocal calls
            calls += 1
            loop.call_soon_threadsafe(started.set)
            assert release.wait(5), 'test did not release probe'
            return {'system': {'cpu_percent': 17}}

        feed = TelemetryFeed(collect, interval=5)
        first = asyncio.create_task(feed.snapshot())
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            requests = [asyncio.create_task(feed.snapshot()) for _ in range(8)]
        finally:
            release.set()
        samples = await asyncio.gather(*requests)
        assert calls == 1
        assert samples[0]['system']['cpu_percent'] == 17
        assert all(sample is samples[0] for sample in samples)

    asyncio.run(run())


def test_probe_failure_is_sanitized_and_expires(monkeypatch):
    now = 10.0
    monkeypatch.setattr(telemetry_feed, 'monotonic', lambda: now)
    monkeypatch.setattr(telemetry_feed, 'time', lambda: 1000 + now)
    calls = 0
    def collect():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError('private probe failure')
        return {'status': 'ok'}

    async def run():
        nonlocal now
        feed = TelemetryFeed(collect, interval=1)
        first = await feed.snapshot()
        assert first['status'] == 'unavailable'
        assert 'private probe failure' not in str(first)
        now = 10.9
        assert await feed.snapshot() is first
        assert first['last_updated'] == 1010.0
        now = 11.0
        second = await feed.snapshot()
        assert second == {'status': 'ok', 'last_updated': 1011.0}
        assert calls == 2

    asyncio.run(run())
