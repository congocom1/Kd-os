"""Hardware-free contracts for the existing provider-session voice path."""
import asyncio
import unittest
from types import SimpleNamespace

from core.kd_pipeline import KDVoicePipeline
from providers.base import Msg
from providers.engine_pipeline import PipelineEngine


class LLM:
    caps = {}

    async def chat(self, messages, tools):
        yield {"text": "Text answer."}


class STT:
    async def transcribe(self, pcm, sample_rate):
        self.received = (pcm, sample_rate)
        return "hello"


class VoiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_unbound_does_not_claim_readiness(self):
        pipe = KDVoicePipeline()
        self.assertFalse(pipe.start())
        self.assertFalse(pipe.state().listening)
        self.assertEqual(pipe.state().stage, "unavailable")

    async def test_muted_before_ingestion_and_text_fallback(self):
        stt = STT()
        engine = PipelineEngine(LLM(), stt)
        pipe = KDVoicePipeline(engine=engine)
        pipe.mute(True)
        pipe.start()
        await pipe.feed_audio({"data": b'\x01\x00' * 20})
        await engine.send_realtime_input(audio=b'\x01\x00')
        self.assertEqual(engine._mic, [])
        self.assertEqual(await pipe.flush_microphone(), "")
        self.assertFalse(hasattr(stt, "received"))
        self.assertTrue(await pipe.send_text("typed"))
        await engine._gen
        events = list(engine._queue._queue)
        self.assertTrue(any(m.server_content and m.server_content.output_transcription for m in events))
        await engine.close()

    async def test_matching_uses_real_pcm_without_fake_confidence(self):
        class Speakers:
            def identify_speaker(self, audio, sample_rate):
                self.audio, self.rate = audio, sample_rate
                return "alice"

            def get_profile(self, sid):
                return SimpleNamespace(name="Alice")
        speakers = Speakers()
        stt = STT()
        engine = PipelineEngine(LLM(), stt, speaker_processor=speakers)
        pcm = b'\x00\x40\x00\xc0'
        await engine.send_realtime_input(audio=SimpleNamespace(data=pcm))
        self.assertEqual(await engine.flush_microphone(), "hello")
        self.assertEqual(stt.received, (pcm, 16000))
        self.assertEqual(speakers.audio.tolist(), [0.5, -0.5])
        self.assertEqual(engine.speaker_name, "Alice")
        self.assertIsNone(engine.speaker_confidence)
        await engine.close()

    async def test_mute_discards_inflight_recognition(self):
        entered, release = asyncio.Event(), asyncio.Event()
        class SlowSTT:
            async def transcribe(self, pcm, rate):
                entered.set()
                await release.wait()
                return "stale"
        engine = PipelineEngine(LLM(), SlowSTT())
        await engine.send_realtime_input(audio=b'\x01\x00')
        task = asyncio.create_task(engine.flush_microphone())
        await entered.wait()
        engine.set_muted(True)
        engine.set_muted(False)
        release.set()
        self.assertEqual(await task, "")
        self.assertEqual(engine._history, [])
        await engine.close()

    async def test_interrupt_drains_audio_and_cancels_followup(self):
        entered = asyncio.Event()
        class SlowLLM:
            caps = {}
            async def chat(self, messages, tools):
                entered.set()
                await asyncio.Event().wait()
                yield {}
        engine = PipelineEngine(SlowLLM(), STT())
        await engine.send_client_content(turns={"parts": [{"text": "hello"}]})
        await entered.wait()
        engine._followup = True
        engine._queue.put_nowait(Msg.audio(b'old'))
        engine._awaiting["old"] = "tool"
        engine.interrupt()
        with self.assertRaises(asyncio.CancelledError):
            await engine._gen
        self.assertFalse(engine._followup)
        self.assertTrue(all(m.data is None for m in engine._queue._queue))
        await engine.send_tool_response(function_responses=[SimpleNamespace(id="old")])
        self.assertTrue(engine._gen.cancelled())
        await engine.close()
        self.assertEqual(list(engine._queue._queue), [None])

    async def test_no_speaker_provider_is_unknown(self):
        engine = PipelineEngine(LLM(), STT())
        await engine.send_realtime_input(audio=b'\x01\x00')
        await engine.flush_microphone()
        self.assertIsNone(engine.speaker_id)
        self.assertIsNone(engine.speaker_confidence)
        await engine.close()

    async def test_text_only_without_speech_dependencies(self):
        engine = PipelineEngine(LLM())
        await engine.send_realtime_input(audio=b'ignored')
        self.assertEqual(engine._mic, [])
        await engine.send_client_content(turns={"parts": [{"text": "typed"}]})
        await engine._gen
        self.assertFalse(engine.caps["audio_out"])
        self.assertEqual(engine._history[-1]["content"], "Text answer.")
        await engine.close()

    async def test_close_ends_receive_even_when_voice_cleanup_fails(self):
        class BrokenTTS:
            async def wait_pending(self):
                raise RuntimeError("cleanup failed")
        engine = PipelineEngine(LLM(), tts=BrokenTTS())
        with self.assertRaises(RuntimeError):
            await engine.close()
        self.assertEqual([m async for m in engine.receive()], [])


if __name__ == "__main__":
    unittest.main()
