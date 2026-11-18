"""Quota exhaustion handling — no more reconnect loops when all Live models are out."""
import time
from unittest.mock import patch

import pytest

from core import gemini as _gemini


class TestIsQuotaError:
    def test_429_is_quota(self):
        assert _gemini.is_quota_error("429 RESOURCE_EXHAUSTED") is True

    def test_1011_is_quota(self):
        assert _gemini.is_quota_error("1011 None. You exceeded your current quota") is True

    def test_exceeded_quota_text_is_quota(self):
        assert _gemini.is_quota_error("You exceeded your current quota") is True

    def test_normal_error_is_not_quota(self):
        assert _gemini.is_quota_error("INVALID_ARGUMENT") is False
        assert _gemini.is_quota_error("NOT_FOUND") is False


class TestAllLiveModelsExhausted:
    def test_not_exhausted_when_any_available(self, monkeypatch):
        # Clear cooldowns
        _gemini._cooldown.clear()
        assert _gemini.all_live_models_exhausted() is False

    def test_exhausted_when_all_cooling(self, monkeypatch):
        now = time.monotonic()
        for m in _gemini.LIVE_MODELS:
            _gemini._cooldown[m] = now + 300  # 5 minutes from now
        assert _gemini.all_live_models_exhausted() is True
        _gemini._cooldown.clear()

    def test_next_available_returns_zero_when_any_available(self):
        _gemini._cooldown.clear()
        assert _gemini.next_live_model_available_in() == 0.0

    def test_next_available_returns_positive_when_all_cooling(self):
        now = time.monotonic()
        for m in _gemini.LIVE_MODELS:
            _gemini._cooldown[m] = now + 60  # 1 minute from now
        result = _gemini.next_live_model_available_in()
        assert 0.0 < result <= 60.0
        _gemini._cooldown.clear()


class TestNoteLiveFailure:
    def test_quota_error_cools_model(self):
        _gemini._cooldown.clear()
        result = _gemini.note_live_failure(
            "models/gemini-3.1-flash-live-preview",
            "1011 None. You exceeded your current quota",
        )
        assert result is True
        assert _gemini._cooling("models/gemini-3.1-flash-live-preview") is True
        _gemini._cooldown.clear()

    def test_non_quota_error_does_not_cool(self):
        _gemini._cooldown.clear()
        result = _gemini.note_live_failure(
            "models/gemini-3.1-flash-live-preview",
            "INVALID_ARGUMENT: bad config",
        )
        assert result is False
        assert _gemini._cooling("models/gemini-3.1-flash-live-preview") is False
        _gemini._cooldown.clear()
