"""
Vision Learner plugin — JARVIS learns from the camera using the Tiny ML engine.

Capture camera frames, label them (e.g. "cup", "laptop", "person"), train a tiny
neural network, and classify what JARVIS sees. All learning is local — frames
and weights never leave this machine.

Actions:
  capture     — grab one camera frame and describe it
  teach       — label the last captured frame: teach(platform="cup") — actually
                teach(label="cup") — store it as training data
  train       — train the ML engine on all labeled frames (epochs=...)
  predict     — capture a frame and classify it using the trained model
  status      — show how many labeled frames per class and training state
  clear       — clear all training data and reset the model

Features are simple: grayscale, resized to 8x8 (=64 inputs), normalized to [0,1].
The model saves to data/vision_learner_model.npz and training data to
data/vision_learner_samples.json so learning persists between sessions.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from core.tiny_ml import TinyML, TinyMLConfig
from core.lazyimport import LazyModule, installed

_CV2 = installed("cv2")
cv2 = LazyModule("cv2")

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_SAMPLES_PATH = _DATA_DIR / "vision_learner_samples.json"
_MODEL_PATH = _DATA_DIR / "vision_learner_model.npz"

_FEATURE_SIZE = 64  # 8x8 grayscale


def _test_camera(values: dict) -> tuple[bool, str]:
    """Probe the configured camera index."""
    import cv2

    idx = int(values.get("camera_index", 0) or 0)
    try:
        cap = cv2.VideoCapture(idx)
        if not cap.isOpened():
            return False, f"Camera {idx} could not be opened."
        for _ in range(3):
            cap.read()
        ret, frame = cap.read()
        cap.release()
        if not ret or frame is None:
            return False, f"Camera {idx} returned no frame."
        h, w = frame.shape[:2]
        return True, f"Camera {idx} OK — {w}x{h}"
    except Exception as e:
        return False, f"Camera {idx} error: {e}"


# ── Plugin settings (shown in ⚙ → PLUGINS → vision_learner) ────────────────
PLUGIN_SETTINGS = {
    "namespace": "vision_learner",
    "title": "Vision Learner",
    "fields": [
        {
            "key": "camera_index",
            "label": "Camera index",
            "type": "number",
            "default": 0,
            "placeholder": "0",
        },
        {
            "key": "feature_size",
            "label": "Feature resolution (pixels per side)",
            "type": "number",
            "default": 8,
            "placeholder": "8",
        },
        {
            "key": "auto_save_model",
            "label": "Auto-save model after training",
            "type": "toggle",
            "default": True,
        },
    ],
    "action": {
        "label": "TEST CAMERA",
        "run": _test_camera,
    },
}


def _ensure_dir() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_samples() -> dict:
    if not _SAMPLES_PATH.exists():
        return {}
    try:
        return json.loads(_SAMPLES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_samples(samples: dict) -> None:
    _ensure_dir()
    _SAMPLES_PATH.write_text(
        json.dumps(samples, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _capture_frame() -> np.ndarray | None:
    """Capture one camera frame. Returns a BGR numpy array or None."""
    if not _CV2:
        return None
    try:
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return None
        for _ in range(5):  # warmup
            cap.read()
        ret, frame = cap.read()
        cap.release()
        if not ret or frame is None:
            return None
        return frame
    except Exception:
        return None


def _frame_to_features(frame: np.ndarray) -> np.ndarray:
    """Convert a BGR frame to a 64-element normalized feature vector."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA)
    vec = small.astype(np.float32).flatten() / 255.0
    return vec


PLUGIN = {
    "name": "vision_learner",
    "description": (
        "Teach JARVIS to recognize things from the camera. capture grabs a "
        "frame, teach(labels it) stores it as training data, train teaches the "
        "tiny neural network, predict classifies a new frame, status shows "
        "progress. All learning is local — nothing leaves your machine."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "'capture', 'teach', 'train', 'predict', 'status', 'clear'",
            },
            "label": {
                "type": "STRING",
                "description": "Name for the class when teaching (e.g. 'cup', 'laptop')",
            },
            "epochs": {
                "type": "STRING",
                "description": "Training epochs (default 500)",
            },
        },
        "required": ["action"],
    },
}

# One model + last captured frame for the session.
_MODEL: TinyML | None = None
_LAST_FEATURES: np.ndarray | None = None


def _get_model() -> TinyML:
    global _MODEL
    if _MODEL is None:
        config = TinyMLConfig(layer_sizes=(32,), learning_rate=0.1, seed=42)
        _MODEL = TinyML(config)
        if _MODEL_PATH.exists():
            try:
                _MODEL = TinyML.load(_MODEL_PATH)
            except Exception:
                pass
    return _MODEL


def run(parameters: dict, player=None, session_memory=None) -> str:
    global _LAST_FEATURES, _MODEL
    action = (parameters.get("action") or "").strip().lower()
    if not action:
        return "Sir, please specify: capture, teach, train, predict, status, or clear."

    try:
        if action == "capture":
            if not _CV2:
                return "Camera unavailable — OpenCV is not installed."
            frame = _capture_frame()
            if frame is None:
                return "I could not read from the camera, sir."
            _LAST_FEATURES = _frame_to_features(frame)
            h, w = frame.shape[:2]
            return (
                f"Captured a frame ({w}x{h}), sir. Use 'teach' to label it, "
                f"or 'train' once you have several examples."
            )

        if action == "teach":
            label = (parameters.get("label") or "").strip()
            if not label:
                return "Sir, please give the frame a label (e.g. 'cup')."
            if _LAST_FEATURES is None:
                return "No frame captured yet, sir. Say 'capture' first."
            samples = _load_samples()
            samples.setdefault(label, [])
            samples[label].append(_LAST_FEATURES.tolist())
            _save_samples(samples)
            total = sum(len(v) for v in samples.values())
            return (
                f"Labeled the frame '{label}', sir. {total} training samples total."
            )

        if action == "train":
            samples = _load_samples()
            if not samples:
                return "No training data yet, sir. Capture and teach some frames first."
            labels = sorted(samples.keys())
            X, y = [], []
            for class_idx, label in enumerate(labels):
                for vec in samples[label]:
                    X.append(vec)
                    y.append(class_idx)
            X_arr = np.array(X, dtype=np.float32)
            y_arr = np.array(y, dtype=np.int64)
            n_classes = len(labels)
            model = _get_model()
            # Rebuild if class count changed
            if model.config.layer_sizes[-1] != n_classes:
                config = TinyMLConfig(
                    layer_sizes=(32, n_classes), learning_rate=0.1, seed=42
                )
                model = TinyML(config)
                _MODEL = model
            epochs = int(parameters.get("epochs") or 500)
            model.train(X_arr, y_arr, epochs=epochs)
            model.save(_MODEL_PATH)
            acc = model.accuracy(X_arr, y_arr)
            return (
                f"Trained on {len(X_arr)} samples across {n_classes} classes, "
                f"sir. Training accuracy: {acc:.0%}."
            )

        if action == "predict":
            if not _CV2:
                return "Camera unavailable — OpenCV is not installed."
            frame = _capture_frame()
            if frame is None:
                return "I could not read from the camera, sir."
            features = _frame_to_features(frame)
            model = _get_model()
            if not model._initialized:
                return "The model hasn't been trained yet, sir."
            proba = model.predict_proba(features.reshape(1, -1))[0]
            pred = int(np.argmax(proba))
            # map back to label
            samples = _load_samples()
            labels = sorted(samples.keys())
            if pred >= len(labels):
                return "The model isn't aligned with training labels yet, sir."
            label = labels[pred]
            confidence = float(proba[pred])
            return (
                f"I see a {label}, sir — confidence {confidence:.0%}."
            )

        if action == "status":
            samples = _load_samples()
            if not samples:
                return "No training data yet, sir."
            lines = [f"{k}: {len(v)} samples" for k, v in sorted(samples.items())]
            total = sum(len(v) for v in samples.values())
            trained = _MODEL is not None and _MODEL._initialized
            return (
                f"Vision learner: {total} samples across {len(samples)} classes.\n"
                + "\n".join(lines)
                + (f"\nModel: trained ({_MODEL.trained_epochs} epochs)"
                   if trained else "\nModel: not yet trained")
            )

        if action == "clear":
            _LAST_FEATURES = None
            _SAMPLES_PATH.unlink(missing_ok=True)
            _MODEL_PATH.unlink(missing_ok=True)
            _MODEL = None
            return "Cleared all vision training data and the model, sir."

        return f"Sir, I don't recognize the action '{action}'."

    except Exception as e:
        return f"Sir, vision_learner failed: {e}"
