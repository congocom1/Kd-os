"""
Tests for the KD upgrade layer.

Every test here is hermetic: feature flags are overridden in-process, and
nothing writes to the user's real config, memory, or window manager.
"""
import json

import numpy as np
import pytest

from core import feature_flags
from core.feature_flags import (
    CONFIG_FILE as FLAG_CONFIG_FILE,
    all_flags,
    is_enabled,
    is_requested,
    override_flag,
    clear_overrides,
)


@pytest.fixture(autouse=True)
def _no_persisted_flags(monkeypatch, tmp_path):
    """Never read or write the developer's real flag file."""
    monkeypatch.setattr(feature_flags, "CONFIG_FILE", tmp_path / "kd_features.json")
    clear_overrides()
    yield
    clear_overrides()


# ── Feature flags ────────────────────────────────────────────────────────────


def test_all_new_features_default_off():
    for name, flag in all_flags().items():
        assert flag.get() is False, f"{name} must default to off"


def test_flags_never_write_to_the_secrets_file(monkeypatch, tmp_path):
    secrets = tmp_path / "api_keys.json"
    secrets.write_text(json.dumps({"gemini_api_key": "SECRET"}))
    monkeypatch.setattr(feature_flags, "CONFIG_FILE", tmp_path / "kd_features.json")

    feature_flags.set_flag("REALTIME_AWARENESS", True)

    # The secrets file is untouched...
    assert json.loads(secrets.read_text()) == {"gemini_api_key": "SECRET"}
    # ...and the flag landed in its own file.
    written = json.loads((tmp_path / "kd_features.json").read_text())
    assert written["feature_realtime_awareness"] is True


def test_protocol_env_var_names_are_honoured(monkeypatch):
    monkeypatch.setenv("KD_REALTIME_CONTEXT_ENABLED", "1")
    monkeypatch.setenv("KD_SPEAKER_IDENTITY_ENABLED", "1")
    monkeypatch.setenv("KD_HOLOGRAPHIC_HUD_ENABLED", "1")
    monkeypatch.setenv("KD_PROACTIVE_INTELLIGENCE_ENABLED", "1")
    monkeypatch.setenv("KD_AUTONOMOUS_ACTIONS_ENABLED", "1")
    monkeypatch.setenv("KD_DYNAMIC_WINDOWS_ENABLED", "1")
    monkeypatch.setenv("KD_PERSISTENT_MEMORY_ENABLED", "1")
    assert is_requested("REALTIME_AWARENESS")
    assert is_requested("MULTI_PERSON_VOICE")
    assert is_requested("INTERACTIVE_HUD")
    assert is_requested("PROACTIVE_INTELLIGENCE")
    assert is_requested("DYNAMIC_WINDOWS")
    assert is_requested("PERSISTENT_MEMORY")
    assert is_requested("TASK_ORCHESTRATION")


def test_env_var_names_map_to_the_protocol_flags():
    """Protocol §5 fixes the env var names; the mapping must not drift."""
    expected = {
        "REALTIME_AWARENESS": "KD_REALTIME_CONTEXT_ENABLED",
        "MULTI_PERSON_VOICE": "KD_SPEAKER_IDENTITY_ENABLED",
        "DYNAMIC_WINDOWS": "KD_DYNAMIC_WINDOWS_ENABLED",
        "PROACTIVE_INTELLIGENCE": "KD_PROACTIVE_INTELLIGENCE_ENABLED",
        "INTERACTIVE_HUD": "KD_HOLOGRAPHIC_HUD_ENABLED",
        "TASK_ORCHESTRATION": "KD_AUTONOMOUS_ACTIONS_ENABLED",
        "PERSISTENT_MEMORY": "KD_PERSISTENT_MEMORY_ENABLED",
    }
    flags = all_flags()
    for flag_name, env_var in expected.items():
        assert flags[flag_name].env_var == env_var


def test_dependency_chain_is_checked_transitively():
    """A flag whose dependency is itself unavailable must stay off.

    TASK_ORCHESTRATION needs PERSISTENT_MEMORY, which needs
    REALTIME_AWARENESS. With the awareness engine off, the orchestrator is
    not usable even though both of its own switches are on.
    """
    override_flag("PERSISTENT_MEMORY", True)
    override_flag("TASK_ORCHESTRATION", True)

    assert is_requested("TASK_ORCHESTRATION") is True
    assert is_enabled("PERSISTENT_MEMORY") is False
    assert is_enabled("TASK_ORCHESTRATION") is False

    override_flag("REALTIME_AWARENESS", True)
    assert is_enabled("PERSISTENT_MEMORY") is True
    assert is_enabled("TASK_ORCHESTRATION") is True


def test_dependency_missing_keeps_feature_inactive():
    # The HUD requires the awareness engine it reads from.
    override_flag("INTERACTIVE_HUD", True)
    assert is_requested("INTERACTIVE_HUD") is True
    assert is_enabled("INTERACTIVE_HUD") is False

    override_flag("REALTIME_AWARENESS", True)
    assert is_enabled("INTERACTIVE_HUD") is True


def test_flag_file_is_not_the_api_keys_file():
    assert FLAG_CONFIG_FILE.name == "kd_features.json"
    assert FLAG_CONFIG_FILE.name != "api_keys.json"


# ── Runtime adapter ──────────────────────────────────────────────────────────


def test_runtime_reports_unavailable_subsystems_when_all_off():
    from core.kd_runtime import KDRuntime
    runtime = KDRuntime()
    status = runtime.status()
    assert status["started"] is False
    assert all(v is False for v in status["subsystems"].values())

    # Operations must degrade, not raise.
    assert runtime.recall("anything") == []
    assert runtime.list_windows() == []
    assert runtime.submit_task("do a thing")["status"] == "unavailable"
    assert runtime.remember("c", "k", "v")["status"] == "unavailable"
    assert runtime.focus_window("x11_1")["status"] == "unavailable"


def test_runtime_start_is_safe_with_everything_off():
    from core.kd_runtime import KDRuntime
    runtime = KDRuntime()
    result = runtime.start()
    assert all(v is False for v in result.values())
    runtime.stop()


# ── Action surface ───────────────────────────────────────────────────────────


def test_kd_action_is_discovered():
    from pathlib import Path

    from core.action_loader import discover_actions
    base = Path(__file__).resolve().parent.parent
    registry = discover_actions(actions_dir=base / "actions",
                                reserved_names=set(),
                                logger=lambda m: None)
    assert registry.has("kd_assistant")


def test_kd_action_answers_honestly_when_disabled():
    from actions.kd_assistant import kd_assistant
    out = kd_assistant("recall", query="holiday plans")
    assert isinstance(out, str)
    # With the flag off there is no enhanced memory, so the tool must not
    # claim it remembered anything.
    assert "unavailable" in out.lower() or "no memories" in out.lower()


def test_kd_action_rejects_unknown_operation():
    from actions.kd_assistant import kd_assistant
    assert "Unknown operation" in kd_assistant("nonsense")


# ── Speaker voice: local embedder ────────────────────────────────────────────


def _tone(freqs, seconds=1.0, sample_rate=16000, amp=0.4):
    t = np.arange(int(seconds * sample_rate)) / sample_rate
    out = np.zeros_like(t)
    for f in freqs:
        out += amp * np.sin(2 * np.pi * f * t)
    return (out.astype(np.float32) / len(freqs))


def _processor(tmp_path):
    """A voice processor with no optional model and no awareness engine."""
    from core import multi_person_voice as mpv
    from cryptography.fernet import Fernet
    proc = mpv.MultiPersonVoiceProcessor.__new__(mpv.MultiPersonVoiceProcessor)
    proc._lock = mpv.threading.RLock()
    proc._profiles = {}
    proc._next_speaker_num = 1
    proc._profiles_dir = tmp_path
    # Test-only key: never access the user's OS keyring or real profile data.
    proc._encryption_key = Fernet.generate_key()
    proc._embedding_model = None
    proc._local_embedder = mpv.SpectralSpeakerEmbedder()
    proc._awareness = None
    proc._event_token = None
    proc._stt_provider = None
    return proc


def test_local_embedder_distinguishes_different_timbres():
    from core.multi_person_voice import SpectralSpeakerEmbedder
    emb = SpectralSpeakerEmbedder()
    low = emb.embed(_tone([120, 240, 360]))
    high = emb.embed(_tone([900, 1800, 2700]))
    assert low.shape == high.shape == (emb.DIM,)
    assert float(np.dot(low, high)) < 0.999


def test_local_embedder_is_stable_for_the_same_voice():
    from core.multi_person_voice import SpectralSpeakerEmbedder
    emb = SpectralSpeakerEmbedder()
    a = emb.embed(_tone([150, 300, 450]))
    b = emb.embed(_tone([150, 300, 450]) * 0.8)      # same voice, different level
    assert float(np.dot(a, b)) > 0.99


def test_enrol_and_identify_without_speechbrain(tmp_path):
    proc = _processor(tmp_path)
    voice_a = _tone([130, 260, 390])
    voice_b = _tone([850, 1700, 2550])

    proc.enroll_speaker("alice", [voice_a], name="Alice")
    proc.enroll_speaker("bob", [voice_b], name="Bob")

    assert proc.identify_speaker(voice_a, threshold=0.5) == "alice"
    assert proc.identify_speaker(voice_b, threshold=0.5) == "bob"
    # An unknown voice must not be force-matched.
    assert proc.identify_speaker(_tone([3000, 3100, 3200]), threshold=0.95) is None


def test_diarization_does_not_alternate_speakers_fictionally(tmp_path):
    """Two utterances by the same voice must share one speaker label."""
    proc = _processor(tmp_path)
    voice = _tone([200, 400, 600], seconds=0.8)
    silence = np.zeros(int(0.6 * 16000), dtype=np.float32)
    audio = np.concatenate([voice, silence, voice])

    result = proc._diarize_energy(audio, 16000)
    speakers = {s.speaker_id for s in result.segments}
    assert len(speakers) == 1, f"same voice split into {speakers}"


def test_enrol_requires_at_least_one_sample(tmp_path):
    proc = _processor(tmp_path)
    with pytest.raises(ValueError):
        proc.enroll_speaker("alice", [], name="Alice")


# ── Memory embeddings: local, and never downloaded ───────────────────────────


def _lexical_provider():
    """An embedding provider with no model loaded (no model, no network)."""
    from core.persistent_memory import EmbeddingProvider
    provider = EmbeddingProvider.__new__(EmbeddingProvider)
    provider.model = None
    provider.dim = EmbeddingProvider.DIM
    return provider


def test_embedding_provider_never_downloads_a_model(monkeypatch):
    """Protocol §6: no automatic large-model downloads."""
    import sys
    import types

    seen = {}

    class FakeSentenceTransformer:
        def __init__(self, name, **kwargs):
            seen["name"] = name
            seen["kwargs"] = kwargs
            if kwargs.get("local_files_only") is not True:
                raise RuntimeError("the memory engine must never download a model")
            raise RuntimeError("no cached model")

    fake = types.ModuleType("sentence_transformers")
    fake.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake)

    from core.persistent_memory import EmbeddingProvider
    provider = EmbeddingProvider()

    assert seen["name"] == "all-MiniLM-L6-v2"
    assert seen["kwargs"].get("local_files_only") is True
    # No cached model -> the local embedding takes over.
    assert provider.model is None
    assert provider.embed("hello").shape == (provider.dim,)


def test_embedding_provider_works_without_sentence_transformers(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    from core.persistent_memory import EmbeddingProvider
    provider = EmbeddingProvider()
    assert provider.model is None
    vector = provider.embed("the user's cat is called Pixel")
    assert np.all(np.isfinite(vector))
    assert pytest.approx(float(np.linalg.norm(vector)), abs=1e-5) == 1.0


def test_local_embedding_finds_related_text():
    """The local fallback must carry real similarity, not just be a hash."""
    provider = _lexical_provider()
    query = provider.embed("the user's cat is called Pixel")
    related = provider.embed("Pixel the cat belongs to the user")
    unrelated = provider.embed("quarterly revenue forecast spreadsheet")

    assert float(np.dot(query, related)) > 0.2
    assert float(np.dot(query, related)) > float(np.dot(query, unrelated))
    assert float(np.dot(query, unrelated)) < 0.2


def test_local_embedding_is_deterministic():
    provider = _lexical_provider()
    a = provider.embed("stable text")
    b = provider.embed("stable text")
    assert np.array_equal(a, b)


# ── Window management: wmctrl output parsing ─────────────────────────────────


def _backend_with_wmctrl_output(line):
    from core.window_manager import XdotoolBackend
    backend = XdotoolBackend.__new__(XdotoolBackend)
    backend._available = True
    backend._wmctrl = "wmctrl"
    backend._xdotool = "xdotool"
    backend._run_wmctrl = lambda args: line
    backend._geometry = lambda wid: {"x": 0, "y": 64, "width": 3840, "height": 2336}
    backend._active_id = lambda: "4194307"
    return backend


def test_wmctrl_line_is_parsed_into_class_and_title():
    line = ("0x01000004  0 532295 chatgpt "
            "(/home/hermes/.config/Codex).Chatgpt  Hermes ChatGPT")
    windows = _backend_with_wmctrl_output(line).enumerate_windows()

    assert len(windows) == 1
    window = windows[0]
    assert window.app_name == "chatgpt"
    assert window.title == "Hermes ChatGPT"
    assert window.pid == 532295
    assert window.window_id == "x11_0x01000004"
    assert window.bounds["width"] == 3840


def test_wmctrl_hex_id_is_converted_for_xdotool():
    from core.window_manager import XdotoolBackend
    assert XdotoolBackend._decimal_id("0x01000004") == str(0x01000004)
    assert XdotoolBackend._decimal_id("4194307") == "4194307"
