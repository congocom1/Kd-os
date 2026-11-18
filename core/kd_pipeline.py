"""Optional UI adapter for an existing PipelineEngine session.

This does not open a microphone, run wake detection, consume session events, or
play sound. main.py remains the sole owner of those operations. Bind its actual
session explicitly; start() alone is not evidence that voice is ready. Calls
must run on the session's event loop. In particular mute must be applied by the
capture owner BEFORE reading/queuing audio (ingestion gating is not hardware
privacy). No second orchestration thread or invented provider API is used.
"""
from dataclasses import dataclass, replace
from typing import Optional


@dataclass
class PipelineState:
    listening: bool = False
    transcribing: bool = False
    thinking: bool = False
    speaking: bool = False
    muted: bool = False
    error: Optional[str] = None
    speaker_id: Optional[str] = None
    speaker_name: Optional[str] = None
    speaker_confidence: Optional[float] = None
    last_transcript: str = ""
    last_response: str = ""
    stage: str = "idle"


class KDVoicePipeline:
    """Session adapter, not an independently runnable voice pipeline.

    The capture owner calls feed_audio/flush_microphone or uses the engine
    directly, and forwards events to observe() from its existing receive loop.
    Playback stays with that owner; speak_callback is retained for constructor
    compatibility but deliberately never called (it would duplicate playback).
    """

    def __init__(self, config=None, speak_callback=None, on_transcript=None,
                 on_response=None, on_state_change=None, *, engine=None):
        self._engine = engine
        self._state = PipelineState()
        self._on_transcript = on_transcript
        self._on_response = on_response
        self._on_state_change = on_state_change
        self._started = False

    def state(self):
        return replace(self._state)

    def _set_state(self, **changes):
        self._state = replace(self._state, **changes)
        if self._on_state_change:
            self._on_state_change(self.state())

    def start(self):
        if self._engine is None:
            self._set_state(stage="unavailable", error="Bind the existing provider session; no capture is started.")
            return False
        self._started = True
        self._engine.set_muted(self._state.muted)
        self._set_state(stage="idle", error=None)
        return True

    def stop(self):
        self._started = False
        if self._engine:
            self._engine.interrupt()
        self._set_state(listening=False, transcribing=False, thinking=False,
                        speaking=False, stage="idle")
        # The session owner, not this adapter, awaits engine.close().

    def mute(self, muted=True):
        if self._engine:
            self._engine.set_muted(muted)
        self._set_state(muted=bool(muted), listening=False,
                        transcribing=False, thinking=False, speaking=False,
                        stage="muted" if muted else "idle")

    def interrupt(self):
        if self._engine:
            self._engine.interrupt()
        self._set_state(listening=False, transcribing=False, thinking=False,
                        speaking=False, stage="idle")

    async def feed_audio(self, audio):
        if self._started and not self._state.muted:
            await self._engine.send_realtime_input(audio=audio)

    async def flush_microphone(self, sample_rate=16000):
        if not self._started or self._state.muted:
            return ""
        return await self._engine.flush_microphone(sample_rate)

    async def send_text(self, text):
        """Typed input works even while muted or without STT/TTS."""
        if not self._started or not text.strip():
            return False
        await self._engine.send_client_content(
            turns={"role": "user", "parts": [{"text": text}]})
        return True

    def observe(self, message):
        """Mirror events; never become a second receive()/playback owner."""
        if not self._started:
            return
        content = message.server_content
        if content is None:
            return
        if content.input_transcription:
            text = content.input_transcription.text
            self._set_state(last_transcript=text, thinking=True, stage="thinking",
                            speaker_id=self._engine.speaker_id,
                            speaker_name=self._engine.speaker_name,
                            speaker_confidence=self._engine.speaker_confidence)
            if self._on_transcript:
                self._on_transcript(text)
        if content.output_transcription:
            text = content.output_transcription.text
            self._set_state(last_response=text)
            if self._on_response:
                self._on_response(text)
        if content.turn_complete or content.interrupted:
            self._set_state(thinking=False, speaking=False, stage="idle")


def create_pipeline(config=None, *, engine=None):
    return KDVoicePipeline(config, engine=engine)
