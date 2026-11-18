"""
Local wake-word detection for JARVIS ("Hey Jarvis").

Design goals:
  • ZERO cost when the feature is off — openwakeword is imported ONLY inside
    start()/install helpers, never at module load. If the user never enables
    wake word, none of this touches the app.
  • ZERO latency on the audio path — the microphone callback only ever does a
    cheap, non-blocking queue push (feed()); the actual model inference runs in
    this module's own background thread, so the real-time audio thread and the
    Gemini stream are never slowed.
  • Fully local & offline — audio fed here never leaves the machine; there is no
    network call except the one-time model download the user triggers from the UI.

openwakeword ships small ONNX models (a few MB each) and runs comfortably on a
CPU. The pretrained wake phrase used here is "Hey Jarvis".
"""
from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

# Pretrained openwakeword model that listens for "Hey Jarvis".
WAKE_MODEL = "hey_jarvis"
# Score in [0,1]; above this counts as a detection. Tunable per environment.
DEFAULT_THRESHOLD = 0.5
# Mic frames arrive at 16 kHz int16; this is just the detector's input rate.
SAMPLE_RATE = 16000
# After a detection, stay quiet this long. A single spoken "hey jarvis" is loud
# across several consecutive audio windows, and each of them clears the
# threshold on its own, so without this one utterance would be reported once
# per window. Long enough to span a phrase, short enough that a second,
# deliberate "hey jarvis" is never smothered by the first.
DETECTION_COOLDOWN = 1.5


def is_installed() -> bool:
    """True if the openwakeword package is importable (no model check)."""
    try:
        import importlib.util
        return importlib.util.find_spec("openwakeword") is not None
    except Exception:
        return False


def is_ready() -> bool:
    """True if openwakeword is installed AND its model files are present on disk.

    This is a cheap, DETERMINISTIC file-existence check. It deliberately does NOT
    construct a Model to probe readiness — doing that is slow and, worse, can clash
    with the detector's own Model when it's already running, which intermittently
    returned False and made the UI flicker to 'not downloaded'. Never raises.
    """
    if not is_installed():
        return False
    try:
        import openwakeword
        models_dir = Path(openwakeword.__file__).resolve().parent / "resources" / "models"
        if not models_dir.is_dir():
            return False
        has_wake = (any(models_dir.glob(f"{WAKE_MODEL}*.onnx"))
                    or any(models_dir.glob(f"{WAKE_MODEL}*.tflite")))
        has_mel = (any(models_dir.glob("melspectrogram*.onnx"))
                   or any(models_dir.glob("melspectrogram*.tflite")))
        has_emb = (any(models_dir.glob("embedding_model*.onnx"))
                   or any(models_dir.glob("embedding_model*.tflite")))
        return bool(has_wake and has_mel and has_emb)
    except Exception:
        return False


def install_and_download(logger: Callable[[str], None] = print,
                         notify: Callable[[str], None] | None = None) -> tuple[bool, str]:
    """
    One-click setup for the UI button: pip-install openwakeword if missing, then
    download the wake model. Returns (ok, message). Never raises — every failure
    is reported through the returned message and the logger.
    """
    _tell = notify or (lambda _msg: None)
    try:
        if not is_installed():
            logger("Wake word: installing openwakeword (one-time)…")
            _tell("Wake word: installing openwakeword (one-time)…")
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", "openwakeword"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            if r.returncode != 0:
                tail = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or [""]
                return False, f"pip install failed: {tail[0][:160]}"
        # Download the pretrained melspectrogram/embedding + wake models.
        logger("Wake word: downloading models…")
        _tell("Wake word: downloading models…")
        try:
            import openwakeword.utils as _u
            try:
                _u.download_models([WAKE_MODEL])
            except TypeError:
                _u.download_models()   # older signature downloads the default set
        except Exception as e:
            return False, f"model download failed: {e}"

        if not is_ready():
            return False, "installed, but the wake model could not be loaded."
        logger("Wake word: ready.")
        return True, "Wake word installed and ready."
    except Exception as e:
        return False, f"setup error: {e}"


def _build_cpu_model(model_path: str):
    """Construct an openwakeword Model pinned to CPU.

    ROOT CAUSE FIX: openwakeword's AudioFeatures (melspectrogram + embedding
    preprocessing) hardcodes providers=["CUDAExecutionProvider",
    "CPUExecutionProvider"]. When onnxruntime-gpu is installed but cuDNN's
    unversioned libcudnn.so is absent, the CUDA session is created fine and
    then EVERY prediction dies inside the Conv kernel — the detector runs
    forever and never hears anything. The wake pipeline is a few-kiloparameter
    model designed for CPUs, so we pin CPU for the sessions created while the
    Model is being constructed. The patch is scoped to construction only and
    restored immediately after.
    """
    from openwakeword.model import Model
    import onnxruntime as _ort

    real_session = _ort.InferenceSession

    def _cpu_session(path, sess_options=None, providers=None, **kwargs):
        return real_session(path, sess_options=sess_options,
                            providers=["CPUExecutionProvider"], **kwargs)

    _ort.InferenceSession = _cpu_session
    try:
        return Model(wakeword_model_paths=[model_path])
    finally:
        _ort.InferenceSession = real_session


class WakeWordDetector:
    """
    Runs the wake model in a dedicated thread. The mic thread calls feed() with
    raw int16 frames; detections invoke on_detect() (called from this thread —
    the callback must marshal to whatever loop/UI it needs).
    """

    def __init__(self, on_detect: Callable[[], None],
                 threshold: float = DEFAULT_THRESHOLD,
                 logger: Callable[[str], None] = print,
                 notify: Callable[[str], None] | None = None):
        self._on_detect = on_detect
        self._threshold = threshold
        self._logger    = logger
        # See PluginRegistry: `logger` is the console and gets everything,
        # `notify` is the activity log and gets only what the user must act on.
        self._notify    = notify or (lambda _msg: None)
        self._queue: queue.Queue = queue.Queue(maxsize=50)
        self._thread: threading.Thread | None = None
        self._cooldown_until: float = 0.0
        self._running = False
        self._model = None
        self._ready = False

    def start(self) -> bool:
        """Load the model and spawn the inference thread. Returns True on success.
        Safe to call again — a no-op if already running. Never raises."""
        if self._running:
            return True
        try:
            from openwakeword.model import Model
            # Resolve the actual pretrained model file (e.g. hey_jarvis_v0.1.onnx)
            # from the openwakeword package's resources directory.
            import openwakeword
            from pathlib import Path as _Path
            models_dir = _Path(openwakeword.__file__).resolve().parent / "resources" / "models"
            model_path = None
            for cand in models_dir.glob(f"{WAKE_MODEL}_*.onnx"):
                model_path = str(cand)
                break
            if model_path is None:
                raise FileNotFoundError(f"no pretrained model for '{WAKE_MODEL}' found in {models_dir}")
            self._model = _build_cpu_model(model_path)
        except Exception as e:
            self._logger(f"Wake word: could not load model — {e}")
            self._notify("Wake word unavailable — use the WAKE NOW button.")
            self._model = None
            return False
        self._running = True
        self._ready = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="WakeWordThread")
        self._thread.start()
        self._logger("Wake word: listening for 'Hey Jarvis'.")
        return True

    def stop(self) -> None:
        self._running = False
        # unblock the thread if it's waiting on the queue
        try:
            self._queue.put_nowait(None)
        except Exception:
            pass
        self._model = None
        self._ready = False
        self._cooldown_until = 0.0

    @property
    def ready(self) -> bool:
        return self._ready

    def feed(self, frame_int16) -> None:
        """Called from the mic callback (real-time thread). Must stay cheap and
        never block — the frame is copied and dropped if the queue is backed up."""
        if not self._running:
            return
        try:
            # frame_int16 is a numpy int16 array (possibly 2-D mono) — flatten to 1-D
            data = frame_int16[:, 0].copy() if getattr(frame_int16, "ndim", 1) > 1 else frame_int16.copy()
            self._queue.put_nowait(data)
        except queue.Full:
            pass
        except Exception:
            pass

    def _loop(self) -> None:
        import numpy as np
        while self._running:
            try:
                frame = self._queue.get()
                if frame is None or not self._running:
                    break
                scores = self._model.predict(np.asarray(frame, dtype=np.int16))
                score = self._jarvis_score(scores)
                if score >= self._threshold:
                    # drain any backlog so we don't double-fire on the same utterance
                    self._drain()
                    if self._in_cooldown():
                        continue
                    self._cooldown_until = time.monotonic() + DETECTION_COOLDOWN
                    try:
                        self._on_detect()
                    except Exception as e:
                        self._logger(f"Wake word: on_detect error — {e}")
            except Exception as e:
                self._logger(f"Wake word: inference error — {e}")

    def _jarvis_score(self, scores) -> float:
        """Pull JARVIS's own score out of a multi-model prediction.

        openwakeword's Model reports a score for every wake model loaded in it,
        and the ones a user-tuned one is loaded next to are named after other
        assistants. So "the highest score" is not this detector's answer — a
        podcast yelling "Alexa" in the next room would wake JARVIS. Pick the
        model whose key names JARVIS, by key regardless of version suffix.

        The fallback for a single loaded model covers a retrained model whose
        key does not spell "jarvis" — there is only one candidate, so it cannot
        be a false wake off someone else's phrase. When several models are
        loaded and none is JARVIS's, the answer is 0.0: stay asleep.
        """
        if not isinstance(scores, dict) or not scores:
            return 0.0
        best = 0.0
        for key, value in scores.items():
            if "jarvis" in str(key).lower():
                try:
                    best = max(best, float(value))
                except (TypeError, ValueError):
                    continue
        if best == 0.0 and len(scores) == 1:
            # A single model whose key does not spell "jarvis" — a retrained
            # one. There is nobody else to be mistaken for, so take it.
            try:
                best = max(float(v) for v in scores.values())
            except (TypeError, ValueError):
                best = 0.0
        return best

    def _in_cooldown(self) -> bool:
        """True if a detection was reported very recently.

        One utterance spans several consecutive windows of audio, each of which
        clears the threshold on its own, so without this a single "hey jarvis"
        is reported once per window. Draining the queue reduces that but cannot
        close it: the frames for the rest of the utterance keep arriving while
        this loop is still catching up.
        """
        return time.monotonic() < self._cooldown_until

    def _drain(self) -> None:
        try:
            while True:
                self._queue.get_nowait()
        except Exception:
            pass
