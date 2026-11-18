"""
core/multi_person_voice.py — Multi-person Voice Recognition (KD Upgrade).

Extends the existing STT pipeline with:
  • Speaker diarization (who spoke when)
  • Speaker enrollment/identification (voice profiles)
  • Real-time speaker tracking via awareness engine
  • Multi-person conversation transcription
  • Zero-regression: gated by MULTI_PERSON_VOICE flag, additive to existing STT

Requires: REALTIME_AWARENESS flag (for event bus integration)
Optional: pyannote.audio for diarization, speechbrain for embeddings
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from core.feature_flags import is_enabled
from core import speaker_encryption
from core.awareness_engine import get_awareness_engine, EventType, VoiceTranscriptPayload

logger = logging.getLogger("jarvis.multi_person_voice")


# ── Local speaker embedding (no optional dependencies) ────────────────────────

class SpectralSpeakerEmbedder:
    """A small, dependency-free speaker embedding.

    speechbrain's ECAPA model is the accurate path, but it is a large
    optional download. This fallback derives a fixed-length descriptor from
    the log-magnitude spectrum of a voice sample: the coarse spectral shape
    (which is what carries most of a person's timbre at this size) plus the
    modulation energy of that shape over time.

    It is deliberately simple and local — no model download, no network, no
    GPU — so speaker enrolment and identification work on a stock install.
    Accuracy is well below a trained x-vector, so identification confidence is
    reported conservatively and unknown speakers stay unknown.
    """

    N_MELS = 24
    N_MFCC = 12
    FRAME = 400          # 25 ms at 16 kHz
    HOP = 160            # 10 ms
    # mfcc mean (12) + mfcc std (12) + modulation (12) + level stats (2)
    DIM = 38

    def embed(self, audio: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
        x = np.asarray(audio, dtype=np.float32).reshape(-1)
        if x.size < self.FRAME:
            x = np.pad(x, (0, self.FRAME - x.size))
        if x.size == 0:
            return np.zeros(self.DIM, dtype=np.float32)

        # Remove DC offset and normalise level so loudness does not dominate.
        x = x - float(np.mean(x))
        peak = float(np.max(np.abs(x)))
        if peak > 1e-6:
            x = x / peak

        n_frames = 1 + (x.size - self.FRAME) // self.HOP
        frames = np.stack([
            x[i * self.HOP: i * self.HOP + self.FRAME]
            for i in range(n_frames)
        ])
        window = np.hanning(self.FRAME).astype(np.float32)
        spectrum = np.abs(np.fft.rfft(frames * window, axis=1))
        log_spec = np.log(spectrum + 1e-8)

        # Mel-like filterbank: triangular bands over a mel scale.
        def hz_to_mel(hz: float) -> float:
            return 2595.0 * np.log10(1.0 + hz / 700.0)

        def mel_to_hz(mel: float) -> float:
            return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)

        n_freq = log_spec.shape[1]
        freqs = np.linspace(0, sample_rate / 2, n_freq)
        mels = np.linspace(hz_to_mel(80.0), hz_to_mel(min(7600.0, sample_rate / 2)),
                           self.N_MELS + 2)
        mel_pts = mel_to_hz(mels)
        filters = np.zeros((self.N_MELS, n_freq), dtype=np.float32)
        for m in range(self.N_MELS):
            left, center, right = mel_pts[m], mel_pts[m + 1], mel_pts[m + 2]
            rising = (freqs - left) / max(center - left, 1e-6)
            falling = (right - freqs) / max(right - center, 1e-6)
            filters[m] = np.clip(np.minimum(rising, falling), 0.0, None)

        mel_energy = log_spec @ filters.T                    # (frames, N_MELS)
        # DCT -> MFCC (the energy term is dropped, as usual)
        n = np.arange(self.N_MELS)
        k = np.arange(self.N_MFCC)
        dct = np.cos(np.pi * np.outer(k + 0.5, n) / self.N_MELS)
        mfcc = mel_energy @ dct.T
        mfcc = (mfcc - mfcc.mean(axis=0)) / (mfcc.std(axis=0) + 1e-6)

        # Temporal modulation of the spectral envelope (speaking rate / rhythm).
        delta = np.diff(mel_energy, axis=0)
        if delta.shape[0] > 0:
            modulation = np.abs(delta).mean(axis=0)
        else:
            modulation = np.zeros(self.N_MELS, dtype=np.float32)

        features = np.concatenate([
            mfcc.mean(axis=0),
            mfcc.std(axis=0),
            modulation[: self.N_MFCC],
            np.array([float(np.mean(x)), float(np.std(x))]),
        ]).astype(np.float32)

        # Pad or trim to a fixed width so profiles are comparable.
        if features.size < self.DIM:
            features = np.pad(features, (0, self.DIM - features.size))
        else:
            features = features[: self.DIM]

        norm = float(np.linalg.norm(features))
        if norm > 1e-8:
            features = features / norm
        return features


# ── Speaker Profile ───────────────────────────────────────────────────────────

@dataclass
class SpeakerProfile:
    """A known speaker with voice characteristics."""
    speaker_id: str
    name: str | None = None
    embedding: np.ndarray | None = None  # Voice embedding for identification
    sample_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "speaker_id": self.speaker_id,
            "name": self.name,
            "embedding": self.embedding.tolist() if self.embedding is not None else None,
            "sample_count": self.sample_count,
            "created_at": self.created_at,
            "last_seen": self.last_seen,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SpeakerProfile":
        embedding = data.get("embedding")
        if embedding is not None:
            embedding = np.array(embedding, dtype=np.float32)
        return cls(
            speaker_id=data["speaker_id"],
            name=data.get("name"),
            embedding=embedding,
            sample_count=data.get("sample_count", 0),
            created_at=data.get("created_at", time.time()),
            last_seen=data.get("last_seen", time.time()),
            metadata=data.get("metadata", {}),
        )


# ── Diarization Result ────────────────────────────────────────────────────────

@dataclass
class DiarizationSegment:
    """A single speaker segment from diarization."""
    start: float
    end: float
    speaker_id: str
    confidence: float = 1.0


@dataclass
class DiarizationResult:
    """Complete diarization result for an audio segment."""
    segments: list[DiarizationSegment]
    num_speakers: int
    duration: float


# ── Multi-Person Voice Processor ──────────────────────────────────────────────

class MultiPersonVoiceProcessor:
    """
    Processes audio for multi-person voice recognition.

    Wraps existing STT provider and adds:
    - Speaker diarization (segmentation by speaker)
    - Speaker identification (matching to known profiles)
    - Real-time speaker tracking via awareness engine events
    """

    def __init__(self, stt_provider=None, *, profiles_dir: Path | None = None,
                 encryption_key: bytes | str | None = None):
        self.stt_provider = stt_provider
        self._lock = threading.RLock()
        self._profiles: dict[str, SpeakerProfile] = {}
        self._next_speaker_num = 1
        self._diarization_backend: str | None = None
        self._diarization_model = None
        self._embedding_model = None
        self._local_embedder = SpectralSpeakerEmbedder()
        self._initialized = False

        # Storage for speaker profiles
        self._profiles_dir = Path(profiles_dir) if profiles_dir is not None else speaker_encryption.PROFILES_DIR
        self._encryption_key = encryption_key

        # Awareness engine integration
        self._awareness = None
        self._event_token: int | None = None

    def initialize(self) -> bool:
        """Initialize diarization and embedding models."""
        if self._initialized:
            return True
        if not is_enabled("MULTI_PERSON_VOICE"):
            logger.info("Multi-person voice not initialized: flag is off")
            return False

        try:
            # Try to load pyannote.audio for diarization
            self._try_load_diarization()
            # Try to load speechbrain for embeddings
            self._try_load_embeddings()
            # Load saved profiles
            self._load_profiles()
            # Connect to awareness engine
            self._connect_awareness()
            self._initialized = True
            logger.info("Multi-person voice processor initialized")
            return True
        except Exception as e:
            logger.warning(f"Multi-person voice initialization failed: {e}")
            return False

    def _try_load_diarization(self) -> None:
        """Try to load pyannote.audio diarization pipeline."""
        try:
            from pyannote.audio import Pipeline
            # Use a pre-trained diarization pipeline
            # Note: Requires HF token for pyannote/segmentation models
            self._diarization_model = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=None  # Will use HF_TOKEN env var if set
            )
            self._diarization_backend = "pyannote"
            logger.info("Loaded pyannote diarization")
        except Exception as e:
            logger.debug(f"pyannote not available: {e}")
            # Fallback: simple energy-based diarization
            self._diarization_backend = "energy"

    def _try_load_embeddings(self) -> None:
        """Try to load speechbrain for speaker embeddings."""
        try:
            from speechbrain.inference.speaker import EncoderClassifier
            self._embedding_model = EncoderClassifier.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb",
                savedir=str(self._profiles_dir / "ecapa_model")
            )
            logger.info("Loaded ECAPA-TDNN speaker embeddings")
        except Exception as e:
            logger.debug(f"speechbrain not available: {e}")

    # ── Embedding helpers ───────────────────────────────────────────────────

    def _embed(self, audio: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
        """Embed one audio sample, preferring the trained model when present.

        Returns a unit-length float32 vector either way, so profiles enrolled
        with one backend stay comparable with the other as long as the same
        backend is used for both enrolment and identification.
        """
        x = np.asarray(audio, dtype=np.float32)
        if x.ndim > 1:
            x = x.mean(axis=1)
        if self._embedding_model is not None:
            try:
                emb = self._embedding_model.encode_batch(
                    torch.tensor(x).unsqueeze(0)
                ).squeeze().cpu().numpy().astype(np.float32)
                norm = float(np.linalg.norm(emb))
                if norm > 1e-8:
                    return emb / norm
            except Exception as e:
                logger.debug(f"neural embedding failed, using local fallback: {e}")
        return self._local_embedder.embed(x, sample_rate)

    def _connect_awareness(self) -> None:
        """Connect to awareness engine for real-time speaker events."""
        if not is_enabled("REALTIME_AWARENESS"):
            return
        try:
            self._awareness = get_awareness_engine()
            if not self._awareness._started:
                self._awareness.start()
            # Watch speaker-change events so an unknown voice spoken through
            # another path (not just our own diarization) still gets a profile.
            self._event_token = self._awareness.register_pattern(
                EventType.VOICE_SPEAKER_CHANGED,
                self._on_speaker_change
            )
        except Exception as e:
            logger.warning(f"Could not connect to awareness engine: {e}")

    def _on_speaker_change(self, events: list) -> None:
        """Handle speaker change events from awareness engine."""
        for ev in events:
            speaker_id = ev.payload.get("speaker_id")
            if speaker_id and speaker_id not in self._profiles:
                # Create unknown speaker profile
                self._create_unknown_speaker(speaker_id)

    def _create_unknown_speaker(self, speaker_id: str) -> SpeakerProfile:
        """Create a profile for an unknown speaker."""
        with self._lock:
            profile = SpeakerProfile(
                speaker_id=speaker_id,
                name=f"Speaker {self._next_speaker_num}",
            )
            self._next_speaker_num += 1
            self._profiles[speaker_id] = profile
            self._save_profile(profile)
            return profile

    # ── Profile Management ──────────────────────────────────────────────────

    def get_profile(self, speaker_id: str) -> SpeakerProfile | None:
        """Get a speaker profile by ID."""
        with self._lock:
            return self._profiles.get(speaker_id)

    def get_or_create_profile(self, speaker_id: str) -> SpeakerProfile:
        """Get existing profile or create new unknown speaker."""
        with self._lock:
            if speaker_id not in self._profiles:
                return self._create_unknown_speaker(speaker_id)
            return self._profiles[speaker_id]

    def enroll_speaker(self, speaker_id: str, audio_samples: list[np.ndarray],
                       name: str | None = None, sample_rate: int = 16000) -> SpeakerProfile:
        """
        Enroll a speaker with voice samples.

        Args:
            speaker_id: Unique identifier for the speaker
            audio_samples: List of audio arrays (16kHz mono)
            name: Optional human-readable name
            sample_rate: Sample rate of the provided samples
        """
        if not audio_samples:
            raise ValueError("At least one audio sample is required to enrol a speaker")

        with self._lock:
            profile = self._profiles.get(speaker_id)
            if not profile:
                profile = SpeakerProfile(speaker_id=speaker_id, name=name)
                self._profiles[speaker_id] = profile
            elif name:
                profile.name = name

            # Compute embeddings for all samples (neural model when present,
            # local spectral embedder otherwise — never a hard failure).
            embeddings = [self._embed(audio, sample_rate) for audio in audio_samples]

            # Average embeddings and re-normalise.
            mean = np.mean(embeddings, axis=0).astype(np.float32)
            norm = float(np.linalg.norm(mean))
            if norm > 1e-8:
                mean = mean / norm
            profile.embedding = mean
            profile.sample_count = len(embeddings)
            profile.last_seen = time.time()

            self._save_profile(profile)
            logger.info(f"Enrolled speaker {speaker_id} ({name or 'unnamed'}) with {len(embeddings)} samples")
            return profile

    def identify_speaker(self, audio: np.ndarray, threshold: float = 0.75,
                         sample_rate: int = 16000) -> str | None:
        """
        Identify speaker from audio using embedding similarity.

        Returns speaker_id if match found above threshold, else None.
        """
        if not self._profiles:
            return None

        # Compute embedding for input audio
        emb = self._embed(audio, sample_rate)
        if not np.any(emb):
            return None

        # Compare with enrolled speakers
        best_match = None
        best_score = -1.0
        for speaker_id, profile in self._profiles.items():
            if profile.embedding is None:
                continue
            # Cosine similarity
            sim = np.dot(emb, profile.embedding) / (
                np.linalg.norm(emb) * np.linalg.norm(profile.embedding)
            )
            if sim > best_score and sim >= threshold:
                best_score = sim
                best_match = speaker_id

        if best_match:
            self._profiles[best_match].last_seen = time.time()
            self._save_profile(self._profiles[best_match])

        return best_match

    def list_profiles(self) -> list[dict]:
        """List all known speaker profiles."""
        with self._lock:
            return [p.to_dict() for p in self._profiles.values()]

    def rename_speaker(self, speaker_id: str, name: str) -> bool:
        """Rename a speaker profile."""
        with self._lock:
            if speaker_id in self._profiles:
                self._profiles[speaker_id].name = name
                self._save_profile(self._profiles[speaker_id])
                return True
            return False

    def delete_speaker(self, speaker_id: str) -> bool:
        """Delete a speaker profile."""
        with self._lock:
            if speaker_id in self._profiles:
                speaker_encryption.delete_profile(speaker_id, profiles_dir=self._profiles_dir)
                del self._profiles[speaker_id]
                return True
            return False

    # ── Diarization ──────────────────────────────────────────────────────────

    def diarize(self, audio: np.ndarray, sample_rate: int = 16000) -> DiarizationResult:
        """
        Perform speaker diarization on audio.

        Returns segments with speaker IDs (may be temporary IDs like 'SPEAKER_00').
        """
        if self._diarization_backend == "pyannote" and self._diarization_model:
            return self._diarize_pyannote(audio, sample_rate)
        else:
            return self._diarize_energy(audio, sample_rate)

    def _diarize_pyannote(self, audio: np.ndarray, sample_rate: int) -> DiarizationResult:
        """Diarize using pyannote.audio."""
        import torch
        from pyannote.core import Annotation

        # Prepare audio for pyannote (expects waveform tensor)
        waveform = torch.from_numpy(audio.astype(np.float32)).unsqueeze(0)
        # Run diarization
        annotation = self._diarization_model({"waveform": waveform, "sample_rate": sample_rate})

        # Convert to our format
        segments = []
        speakers = set()
        for segment, _, speaker in annotation.itertracks(yield_label=True):
            segments.append(DiarizationSegment(
                start=segment.start,
                end=segment.end,
                speaker_id=speaker,
                confidence=1.0
            ))
            speakers.add(speaker)

        return DiarizationResult(
            segments=segments,
            num_speakers=len(speakers),
            duration=audio.shape[-1] / sample_rate
        )

    def _diarize_energy(self, audio: np.ndarray, sample_rate: int,
                        frame_size: int = 1600, hop_size: int = 800,
                        energy_threshold: float = 0.01,
                        cluster_threshold: float = 0.72) -> DiarizationResult:
        """
        Energy-gated diarization with spectral clustering.

        1. Split the audio into voiced regions using frame energy.
        2. Embed each voiced region and group regions whose embeddings are
           similar (cosine >= cluster_threshold) under one speaker.

        The earlier version assigned speaker IDs by ALTERNATING between two
        labels, which produced plausible-looking but fictional diarization —
        two consecutive utterances by the same person were reported as two
        different people. This groups by actual acoustic similarity instead.
        """
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        if audio.size < frame_size:
            return DiarizationResult(segments=[], num_speakers=0,
                                     duration=audio.size / max(sample_rate, 1))

        # Compute frame energies
        num_frames = (len(audio) - frame_size) // hop_size + 1
        energies = np.zeros(num_frames)
        for i in range(num_frames):
            start = i * hop_size
            frame = audio[start:start + frame_size]
            energies[i] = np.mean(frame ** 2)

        # Find contiguous voiced regions.
        voiced = energies > energy_threshold
        regions: list[tuple[int, int]] = []
        start_idx = None
        for i, is_voiced in enumerate(voiced):
            if is_voiced and start_idx is None:
                start_idx = i
            elif not is_voiced and start_idx is not None:
                regions.append((start_idx, i))
                start_idx = None
        if start_idx is not None:
            regions.append((start_idx, num_frames))

        # Merge regions separated by a short gap (a pause inside one turn).
        min_gap_frames = max(1, int(0.20 * sample_rate / hop_size))
        merged: list[tuple[int, int]] = []
        for region in regions:
            if merged and region[0] - merged[-1][1] <= min_gap_frames:
                merged[-1] = (merged[-1][0], region[1])
            else:
                merged.append(region)

        # Cluster the regions by embedding similarity.
        clusters: list[dict] = []       # {"centroid": vec, "regions": [...]}
        segments: list[DiarizationSegment] = []
        for (a, b) in merged:
            s = a * hop_size
            e = min(len(audio), b * hop_size + frame_size)
            if e - s < sample_rate * 0.15:
                continue
            emb = self._embed(audio[s:e], sample_rate)
            best_cluster = None
            best_sim = -1.0
            for cluster in clusters:
                sim = float(np.dot(emb, cluster["centroid"]))
                if sim > best_sim:
                    best_sim = sim
                    best_cluster = cluster
            if best_cluster is not None and best_sim >= cluster_threshold:
                best_cluster["regions"].append((s, e))
                # Update the centroid incrementally.
                n = len(best_cluster["regions"])
                best_cluster["centroid"] = (
                    (best_cluster["centroid"] * (n - 1) + emb) / n
                ).astype(np.float32)
            else:
                clusters.append({"centroid": emb, "regions": [(s, e)]})

        # Emit one segment per region, labelled by its cluster.
        for cluster in clusters:
            label = f"SPEAKER_{clusters.index(cluster):02d}"
            for (s, e) in cluster["regions"]:
                segments.append(DiarizationSegment(
                    start=s / sample_rate,
                    end=e / sample_rate,
                    speaker_id=label,
                    confidence=0.7,
                ))
        segments.sort(key=lambda seg: seg.start)

        return DiarizationResult(
            segments=segments,
            num_speakers=len(clusters),
            duration=len(audio) / sample_rate
        )

    # ── Transcription with Speaker Labels ────────────────────────────────────

    def transcribe_with_speakers(self, audio: np.ndarray, sample_rate: int = 16000) -> list[dict]:
        """
        Transcribe audio with speaker labels.

        Returns list of dicts: {start, end, speaker_id, speaker_name, text, confidence}
        """
        if not self.stt_provider:
            raise RuntimeError("No STT provider configured")

        # Step 1: Diarize
        diarization = self.diarize(audio, sample_rate)

        # Step 2: Transcribe each segment
        results = []
        for segment in diarization.segments:
            # Extract segment audio
            start_sample = int(segment.start * sample_rate)
            end_sample = int(segment.end * sample_rate)
            seg_audio = audio[start_sample:end_sample]

            if len(seg_audio) < sample_rate * 0.1:  # Skip very short segments
                continue

            # Transcribe
            try:
                # Use STT provider's transcribe method
                if hasattr(self.stt_provider, 'transcribe'):
                    transcript = self.stt_provider.transcribe(seg_audio, sample_rate)
                else:
                    transcript = ""
            except Exception as e:
                logger.warning(f"Transcription failed for segment: {e}")
                transcript = ""

            # Identify speaker if we have enrolled profiles
            speaker_id = segment.speaker_id
            speaker_name = None
            if self._profiles:
                identified = self.identify_speaker(seg_audio, sample_rate=sample_rate)
                if identified:
                    speaker_id = identified
                    profile = self._profiles.get(identified)
                    if profile:
                        speaker_name = profile.name

            # Get or create profile
            profile = self.get_or_create_profile(speaker_id)
            if not speaker_name:
                speaker_name = profile.name

            results.append({
                "start": segment.start,
                "end": segment.end,
                "speaker_id": speaker_id,
                "speaker_name": speaker_name,
                "text": transcript,
                "confidence": segment.confidence,
            })

            # Publish to awareness engine
            if self._awareness:
                payload = VoiceTranscriptPayload(
                    text=transcript,
                    speaker_id=speaker_id,
                    confidence=segment.confidence,
                )
                self._awareness.publish(
                    EventType.VOICE_TRANSCRIPT,
                    payload.__dict__
                )
                # Track the active speaker so the HUD and agents can ask
                # "who is speaking" without re-running diarization.
                self._awareness.publish(
                    EventType.VOICE_SPEAKER_CHANGED,
                    {"speaker_id": speaker_id,
                     "speaker_name": speaker_name,
                     "confidence": segment.confidence},
                )

        return results

    # ── Profile Persistence ──────────────────────────────────────────────────

    def _save_profile(self, profile: SpeakerProfile) -> None:
        """Save encrypted only; failures propagate without changing disk data.

        Legacy files are read-only here. Migration requires a separate explicit
        call to speaker_encryption.save_profile(migrate_legacy=True).
        """
        try:
            encrypted = speaker_encryption.EncryptedSpeakerProfile.from_dict(
                profile.to_dict(), allow_legacy=True)
            speaker_encryption.save_profile(encrypted, profiles_dir=self._profiles_dir,
                                            key=getattr(self, "_encryption_key", None))
        except Exception as e:
            logger.warning(f"Failed to save speaker profile: {e}")
            raise

    def _load_profiles(self) -> None:
        """Load all speaker profiles from disk."""
        with self._lock:
            for profile_file in self._profiles_dir.glob("*.json"):
                try:
                    stored = speaker_encryption.load_profile(
                        profile_file.stem, profiles_dir=self._profiles_dir,
                        key=getattr(self, "_encryption_key", None), allow_legacy=True)
                    if stored is None:
                        continue
                    profile = SpeakerProfile.from_dict(stored.to_dict())
                    self._profiles[profile.speaker_id] = profile
                    # Update next speaker number
                    if profile.speaker_id.startswith("SPEAKER_"):
                        num = int(profile.speaker_id.split("_")[1])
                        self._next_speaker_num = max(self._next_speaker_num, num + 1)
                except Exception as e:
                    logger.warning(f"Failed to load profile {profile_file}: {e}")
            logger.info(f"Loaded {len(self._profiles)} speaker profiles")

    # ── Cleanup ──────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """Clean shutdown."""
        if self._event_token and self._awareness:
            # Would need unregister method on awareness engine
            pass
        self._initialized = False


# ── Convenience: Global Processor Instance ───────────────────────────────────

_processor: MultiPersonVoiceProcessor | None = None


def get_multi_person_voice(stt_provider=None) -> MultiPersonVoiceProcessor | None:
    """Get or create the global multi-person voice processor."""
    global _processor
    if not is_enabled("MULTI_PERSON_VOICE"):
        return None
    if _processor is None:
        _processor = MultiPersonVoiceProcessor(stt_provider)
        _processor.initialize()
    return _processor


# ── Import torch lazily (only needed for embeddings) ──────────────────────────

try:
    import torch
except ImportError:
    torch = None  # type: ignore