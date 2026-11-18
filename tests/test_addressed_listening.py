"""Exercise the actual mic callback without Qt, devices or cloud credentials."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import threading

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / 'main.py').read_text())


def load_function(name, namespace=None):
    node = next(n for n in ast.walk(TREE)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    scope = dict(namespace or {})
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROOT / 'main.py'), 'exec'), scope)
    return scope[name]


def assistant(**overrides):
    obj = SimpleNamespace(
        ui=SimpleNamespace(muted=False, set_audio_level=Mock(), set_state=Mock()),
        _phone_active=False, _speaking_lock=threading.Lock(), _is_speaking=False,
        _wake_enabled=True, _awake=False, _wake_detector=Mock(),
        _tail_active=lambda: False, _ptt_enabled=False, _ptt_held=False,
        _echo=SimpleNamespace(_hist=[]), out_queue=SimpleNamespace(put_nowait=Mock()),
        _events=None, wake=Mock())
    obj.session = object()
    obj.__dict__.update(overrides)
    obj._queue_microphone_audio = lambda data: load_function(
        '_queue_microphone_audio', {'asyncio': asyncio})(obj, data)
    return obj


def callback(obj):
    loop = SimpleNamespace(call_soon_threadsafe=lambda fn, item: fn(item))
    return load_function('callback', {'self': obj, 'loop': loop, '_pcm_level': lambda _: 0.0})


def test_sleeping_audio_stays_local():
    obj = assistant()
    callback(obj)(np.zeros((1280, 1), dtype=np.int16), 1280, None, None)
    obj._wake_detector.feed.assert_called_once()
    obj.out_queue.put_nowait.assert_not_called()


@pytest.mark.parametrize('change', [
    {'_is_speaking': True}, {'_phone_active': True},
    {'_tail_active': lambda: True}, {'_ptt_enabled': True},
    {'ui': SimpleNamespace(muted=True)},
])
def test_blocked_audio_reaches_neither_detector_nor_cloud(change):
    obj = assistant(**change)
    callback(obj)(np.zeros((1280, 1), dtype=np.int16), 1280, None, None)
    obj._wake_detector.feed.assert_not_called()
    obj.out_queue.put_nowait.assert_not_called()


def test_awake_request_reaches_queue():
    obj = assistant(_awake=True)
    callback(obj)(np.ones((1280, 1), dtype=np.int16), 1280, None, None)
    obj.out_queue.put_nowait.assert_called_once()
    obj._wake_detector.feed.assert_not_called()


def test_completed_answer_closes_gate_without_stopping_playback():
    obj = assistant(_awake=True, _is_speaking=True)
    load_function('_finish_voice_request')(obj)
    assert not obj._awake
    assert obj._is_speaking


@pytest.mark.parametrize('change', [{'_ptt_held': True}, {'_phone_active': True}, {'_wake_enabled': False}])
def test_explicit_continuous_sessions_remain_open(change):
    obj = assistant(_awake=True, **change)
    load_function('_finish_voice_request')(obj)
    assert obj._awake


def test_late_detection_cannot_undo_mute():
    obj = assistant(ui=SimpleNamespace(muted=True))
    load_function('_on_wake_detected')(obj)
    obj.wake.assert_not_called()


def test_wake_mode_default_and_opt_out(monkeypatch):
    from memory import config_manager
    monkeypatch.setattr(config_manager, 'load_api_keys', lambda: {})
    assert config_manager.get_wake_word_enabled() is True
    monkeypatch.setattr(config_manager, 'load_api_keys', lambda: {'wake_word_enabled': False})
    assert config_manager.get_wake_word_enabled() is False


def test_detector_field_initialized_before_startup():
    source = (ROOT / 'main.py').read_text()
    assert source.index('self._wake_detector: WakeWordDetector | None = None') < source.index('if self._wake_enabled and not self._ensure_wake_detector():')


def test_stale_desktop_audio_is_not_sent_after_sleep():
    import asyncio

    async def check():
        class Queue:
            def __init__(self):
                self.once = False

            async def get(self):
                if self.once:
                    raise asyncio.CancelledError
                self.once = True
                return {'source': 'desktop', 'data': b'old'}

        obj = assistant(out_queue=Queue(), session=SimpleNamespace(send_realtime_input=Mock()))
        with pytest.raises(asyncio.CancelledError):
            await load_function('_send_realtime')(obj)
        obj.session.send_realtime_input.assert_not_called()

    asyncio.run(check())


def test_awake_offline_audio_is_discarded():
    obj = assistant(_awake=True, session=None)
    callback(obj)(np.ones((1280, 1), dtype=np.int16), 1280, None, None)
    obj.out_queue.put_nowait.assert_not_called()


def test_full_audio_queue_does_not_raise():
    obj = assistant(_awake=True)
    obj.out_queue.put_nowait.side_effect = asyncio.QueueFull
    obj._queue_microphone_audio(b"audio")


def test_detection_is_dispatched_and_rechecks_mute():
    scheduled = []
    obj = assistant(_loop=SimpleNamespace(
        is_running=lambda: True, call_soon_threadsafe=scheduled.append))
    obj._apply_wake_detection = lambda: load_function('_apply_wake_detection')(obj)
    load_function('_on_wake_detected')(obj)
    obj.wake.assert_not_called()
    assert len(scheduled) == 1
    obj.ui.muted = True
    scheduled.pop()()
    obj.wake.assert_not_called()
    obj.ui.muted = False
    obj._apply_wake_detection()
    obj.wake.assert_called_once_with(reason='wake word')


def test_microphone_runs_before_connection_and_is_cleaned_up():
    async def check():
        started = asyncio.Event()
        stopped = asyncio.Event()

        async def mic():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        async def watch():
            await asyncio.Event().wait()

        async def sessions():
            await asyncio.wait_for(started.wait(), 1)
            raise RuntimeError('connection failed')

        obj = assistant(_keep_microphone_open=mic, _run_sleep_watch=watch,
                        _run_sessions=sessions)
        with pytest.raises(RuntimeError, match='connection failed'):
            await load_function('run', {'asyncio': asyncio})(obj)
        assert stopped.is_set()
        obj._wake_detector.stop.assert_called_once()

    asyncio.run(check())


def test_session_does_not_spawn_duplicate_microphone_or_reset_wake():
    node = next(n for n in ast.walk(TREE)
                if isinstance(n, ast.AsyncFunctionDef) and n.name == '_run_sessions')
    source = ast.unparse(node)
    assert 'self._listen_audio()' not in source
    assert 'self._awake = False' not in source
    assert 'QUOTA_ERROR:' not in source
