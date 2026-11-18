"""Timing statistics are exact for ordinary inputs and don't keep a sample log."""

from concurrent.futures import ThreadPoolExecutor

from core import metrics


def test_timing_stats_use_constant_storage_and_count_concurrent_updates(monkeypatch):
    monkeypatch.setattr(metrics, '_timings', {})
    name = 'test.time'
    assert metrics.Metrics.get_timings(name) == {'count': 0, 'min': 0, 'max': 0, 'avg': 0}
    metrics.record_timing(name, 0.0)
    accumulator = metrics._timings[name]

    def record_batch():
        for duration in (1.5, 2.5) * 500:
            metrics.record_timing(name, duration)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: record_batch(), range(4)))
    assert metrics._timings[name] is accumulator
    assert metrics.Metrics.get_timings(name) == {
        'count': 4001, 'min': 0.0, 'max': 2.5, 'avg': 8000 / 4001,
    }
