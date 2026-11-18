"""Regression: wake word must predict on CPU even when onnxruntime-gpu is
installed and cuDNN's unversioned libcudnn.so is absent (the CUDA provider
created sessions fine, then every predict() died inside Conv — the detector
ran forever and never heard a thing).

Fails without core.wake_word._build_cpu_model on such a machine.
"""
import numpy as np
import pytest

pytest.importorskip("openwakeword")
pytest.importorskip("onnxruntime")

import openwakeword
from pathlib import Path

from core.wake_word import WAKE_MODEL, _build_cpu_model


def _model_path() -> Path:
    models_dir = Path(openwakeword.__file__).resolve().parent / "resources" / "models"
    for cand in models_dir.glob(f"{WAKE_MODEL}_*.onnx"):
        return cand
    pytest.skip("wake model not downloaded")


def test_cpu_model_predicts_without_cudnn():
    model = _build_cpu_model(str(_model_path()))
    scores = model.predict(np.zeros(16000, dtype=np.int16))
    assert isinstance(scores, dict) and scores
    assert all(0.0 <= float(v) <= 1.0 for v in scores.values())
    # Preprocessing sessions must be CPU-bound, not CUDA-first.
    af = getattr(model, "preprocessor", None)
    if af is not None and hasattr(af, "melspec_model"):
        assert af.melspec_model.get_providers() == ["CPUExecutionProvider"]
