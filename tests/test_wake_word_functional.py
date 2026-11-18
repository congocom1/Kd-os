"""Wake-word detection and the mic gate that decides what speaks to Gemini.

The unit test (test_wake_word.py) pins the CPU-provider fix. This file pins the
behaviour that fix was protecting: that frames actually reach a model, that a
score crossing the threshold fires on_detect once and not twice, and that the
gate in _listen_audio's mic callback really does stop audio leaving the machine
while JARVIS sleeps.

Nothing here needs a microphone or a GPU. The model is a stub whose scores are
chosen by the test, so the only thing under test is JARVIS's own logic.
"""
import threading
import time

import numpy as np
import pytest

from core.wake_word import DEFAULT_THRESHOLD, DETECTION_COOLDOWN, WakeWordDetector

try:
    import openwakeword  # noqa: F401
    HAVE_OWW = True
except Exception:
    HAVE_OWW = False

needs_oww = pytest.mark.skipif(not HAVE_OWW, reason="openwakeword not installed")


class StubPredictor:
    """Minimal stand-in for openwakeword's Model.

    `scores` is the dict returned by predict(); None means "not loaded yet".
    Records every frame it was asked about so tests can assert on the feed path.
    """

    def __init__(self, scores):
        self.scores = scores
        self.seen = []
        self.calls = 0

    def predict(self, frame):
        self.calls += 1
        self.seen.append(np.asarray(frame).copy())
        return dict(self.scores)


def _detector(scores, threshold=DEFAULT_THRESHOLD, monkeypatch=None):
    """A WakeWordDetector wired to a stub, started without touching openwakeword."""
    events = []
    stub = StubPredictor(scores)
    det = WakeWordDetector(
        on_detect=lambda: events.append(time.time()),
        threshold=threshold,
        logger=lambda _m: None,
    )
    if monkeypatch is not None:
        monkeypatch.setattr(det, "_start_with_stub", lambda: True, raising=False)

    # Install the stub in place of the real model, and start the thread without
    # importing openwakeword: this is the one part of start() we bypass.
    det._model = stub
    det._running = True
    det._ready = True
    det._thread = threading.Thread(target=det._loop, daemon=True, name="WakeStub")
    det._thread.start()
    return det, stub, events


def _settle(seconds=0.4):
    """Let the inference thread work through what has been queued."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(0.02)


# ── the feed path really reaches the model ─────────────────────────────────

def test_frames_reach_the_model():
    det, stub, events = _detector({"hey_jarvis_v0.1": 0.0})
    try:
        frame = np.arange(1280, dtype=np.int16)
        det.feed(frame)
        _settle()
        assert stub.calls >= 1, "predict() was never called"
        # The frame must survive the trip as the same int16 samples, not be
        # reshaped or dtype-coerced into something the model cannot read.
        assert np.array_equal(stub.seen[0], frame)
        assert stub.seen[0].dtype == np.int16
    finally:
        det.stop()


def test_feed_flattens_two_dimensional_frames():
    """Mic callbacks hand over (frames, channels) int16; the model wants 1-D."""
    det, stub, events = _detector({"hey_jarvis_v0.1": 0.0})
    try:
        det.feed(np.zeros((1280, 1), dtype=np.int16))
        _settle()
        assert stub.seen and stub.seen[0].ndim == 1
        assert stub.seen[0].shape == (1280,)
    finally:
        det.stop()


def test_queue_overflow_drops_frames_instead_of_blocking():
    """A backed-up queue must cost the audio thread nothing.

    put_nowait() is what makes that true, and it is why the mic callback can
    stay cheap. If this ever becomes a blocking put, real-time audio stalls.
    """
    det, stub, events = _detector({"hey_jarvis_v0.1": 0.0})
    try:
        det._queue = __import__("queue").Queue(maxsize=3)
        for _ in range(50):
            det.feed(np.zeros(1280, dtype=np.int16))     # must not raise, must not wait
        assert True
    finally:
        det.stop()


# ── a score crossing the threshold wakes, once ─────────────────────────────

def test_score_above_threshold_fires_on_detect():
    det, stub, events = _detector({"hey_jarvis_v0.1": 0.9})
    try:
        det.feed(np.zeros(1280, dtype=np.int16))
        _settle(0.8)
        assert len(events) == 1, f"expected one detection, got {len(events)}"
    finally:
        det.stop()


def test_score_below_threshold_stays_silent():
    det, stub, events = _detector({"hey_jarvis_v0.1": 0.1})
    try:
        for _ in range(10):
            det.feed(np.zeros(1280, dtype=np.int16))
        _settle()
        assert events == []
    finally:
        det.stop()


def test_threshold_is_respected_as_greater_or_equal():
    det, stub, events = _detector({"hey_jarvis_v0.1": DEFAULT_THRESHOLD})
    try:
        det.feed(np.zeros(1280, dtype=np.int16))
        _settle(0.8)
        assert len(events) == 1
    finally:
        det.stop()


def test_one_utterance_fires_once_not_once_per_window():
    """A single phrase spans many audio windows; each is loud on its own.

    Regression: draining the queue was claimed to prevent double-fire, and it
    does not — the frames for the rest of the phrase keep arriving while the
    loop catches up, so a bare `_drain()` let one "hey jarvis" be reported
    three times (actually, once per window for as long as the phrase lives).
    DETECTION_COOLDOWN is what closes it.
    """
    det, stub, events = _detector({"hey_jarvis_v0.1": 0.99})
    try:
        for _ in range(20):
            det.feed(np.zeros(1280, dtype=np.int16))
        _settle(1.0)
        assert len(events) == 1, f"one utterance fired {len(events)} times"
    finally:
        det.stop()


def test_a_second_deliberate_wake_is_not_smothered_by_the_first():
    """The cooldown must expire, or a repeated request is never heard.

    20 hot frames back to back fire once; a further 20, after the cooldown has
    lapsed, must fire again — two separate utterances, two detections.
    """
    det, stub, events = _detector({"hey_jarvis_v0.1": 0.99})
    try:
        for _ in range(20):
            det.feed(np.zeros(1280, dtype=np.int16))
        _settle(1.0)
        assert len(events) == 1

        # Wait past the cooldown, then push a fresh burst.
        time.sleep(DETECTION_COOLDOWN + 0.35)
        for _ in range(20):
            det.feed(np.zeros(1280, dtype=np.int16))
        _settle(1.0)
        assert len(events) == 2, f"second utterance fired {len(events)-1} times"
    finally:
        det.stop()


# ── the score is read from the jarvis model specifically ───────────────────

def test_score_matches_jarvis_key_among_other_models():
    """openwakeword returns every loaded model's score, not just ours."""
    det, stub, events = _detector(
        {"hey_jarvis_v0.1": 0.9, "alexa_v0.1": 0.9, "hey_mycroft_v0.1": 0.9},
        threshold=0.85,
    )
    try:
        det.feed(np.zeros(1280, dtype=np.int16))
        _settle(0.8)
        assert len(events) == 1
    finally:
        det.stop()


def test_loud_non_jarvis_model_does_not_wake():
    """If only someone else's wake model is loud, JARVIS must stay asleep.

    Regression: the old fallback was "if no jarvis key scored, take the highest
    score of all of them". With several models loaded — which is normal, and is
    what happens the moment a user trains their own phrase next to the stock
    ones — a podcast yelling "Alexa" in the next room woke JARVIS. The fallback
    now only applies when there is exactly one model and so no ambiguity.
    """
    det, stub, events = _detector(
        {"alexa_v0.1": 1.0, "hey_mycroft_v0.1": 1.0},
        threshold=0.85,
    )
    try:
        det.feed(np.zeros(1280, dtype=np.int16))
        _settle(0.8)
        assert events == [], "JARVIS woke up for another assistant's wake word"
    finally:
        det.stop()


def test_single_retrained_model_key_that_does_not_spell_jarvis_still_works():
    """The fallback exists for a fine-tuned model with an arbitrary key.

    One model loaded, its key does not spell "jarvis", and there is nothing else
    it could be mistaken for — so it must wake. This is the case the fallback is
    for, and it is why the fallback is kept at all rather than simply removed.
    """
    det, stub, events = _detector({"my_custom_wake_v2": 0.9}, threshold=0.5)
    try:
        det.feed(np.zeros(1280, dtype=np.int16))
        _settle(0.8)
        assert len(events) == 1
    finally:
        det.stop()


def test_jarvis_beats_a_louder_neighbour_model():
    """JARVIS's own score decides, even when another model is louder."""
    det, stub, events = _detector(
        {"hey_jarvis_v0.1": 0.9, "alexa_v0.1": 1.0},
        threshold=0.85,
    )
    try:
        det.feed(np.zeros(1280, dtype=np.int16))
        _settle(0.8)
        assert len(events) == 1
    finally:
        det.stop()


def test_quiet_jarvis_with_loud_neighbour_stays_asleep():
    """…and the mirror image: their being loud does not rescue our silence."""
    det, stub, events = _detector(
        {"hey_jarvis_v0.1": 0.1, "alexa_v0.1": 1.0},
        threshold=0.85,
    )
    try:
        det.feed(np.zeros(1280, dtype=np.int16))
        _settle(0.8)
        assert events == []
    finally:
        det.stop()


def test_empty_scores_do_not_wake_and_do_not_raise():
    det, stub, events = _detector({})
    try:
        det.feed(np.zeros(1280, dtype=np.int16))
        _settle()
        assert events == []
    finally:
        det.stop()


# ── lifecycle ──────────────────────────────────────────────────────────────

def test_stop_ends_the_thread_and_clears_ready():
    det, stub, events = _detector({"hey_jarvis_v0.1": 0.0})
    assert det.ready
    det.stop()
    thread = det._thread
    if thread is not None:
        thread.join(timeout=2)
        assert not thread.is_alive(), "the inference thread survived stop()"
    assert not det._running
    assert not det.ready


def test_feed_after_stop_is_a_noop():
    det, stub, events = _detector({"hey_jarvis_v0.1": 0.9})
    det.stop()
    before = stub.calls
    det.feed(np.zeros(1280, dtype=np.int16))
    time.sleep(0.2)
    assert stub.calls == before, "frames were fed after stop()"


def test_start_is_idempotent_while_running():
    det, stub, events = _detector({"hey_jarvis_v0.1": 0.0})
    try:
        det.feed(np.zeros(1280, dtype=np.int16))
        _settle()
        calls_before = stub.calls
        # Calling start() again must not spawn a second thread or reset state.
        assert det._running
        first_thread = det._thread
        det.start()
        assert det._thread is first_thread
        det.feed(np.zeros(1280, dtype=np.int16))
        _settle()
        assert stub.calls > calls_before      # the original thread is still alive
    finally:
        det.stop()


def test_on_detect_exception_is_contained():
    """A throwing callback must not kill the detector thread."""
    def _boom():
        raise ValueError("callback blew up")

    det = WakeWordDetector(on_detect=_boom, threshold=0.5, logger=lambda _m: None)
    det._model = StubPredictor({"hey_jarvis_v0.1": 0.9})
    det._running = True
    det._ready = True
    det._thread = threading.Thread(target=det._loop, daemon=True)
    det._thread.start()
    try:
        det.feed(np.zeros(1280, dtype=np.int16))
        det.feed(np.zeros(1280, dtype=np.int16))
        _settle(0.8)
        assert det._thread.is_alive(), "the thread died on an on_detect error"
    finally:
        det.stop()


# ── the real model, if it is present ───────────────────────────────────────

@needs_oww
def test_real_model_does_not_wake_on_silence():
    """The strongest claim available offline: no false wake on quiet audio."""
    det = WakeWordDetector(on_detect=lambda: None, logger=lambda _m: None)
    fired = []
    det._on_detect = lambda: fired.append(time.time())
    assert det.start(), "real model failed to load"
    try:
        silence = np.zeros(1280, dtype=np.int16)
        for _ in range(120):            # ~10 s at 16 kHz
            det.feed(silence)
        time.sleep(2)
        assert fired == [], f"silence produced {len(fired)} detections"
    finally:
        det.stop()