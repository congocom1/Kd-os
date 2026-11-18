"""Tests for JARVIS core modules."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_tiny_ml():
    """Test the tiny ML engine."""
    from core.tiny_ml import TinyML, TinyMLConfig
    import numpy as np

    X = np.array([[0, 0], [0, 1], [1, 0], [1, 1]], dtype=np.float32)
    y = np.array([0, 1, 1, 0])

    ml = TinyML(TinyMLConfig((8, 2), learning_rate=0.5, seed=42))
    ml.train(X, y, epochs=5000)

    assert ml.accuracy(X, y) >= 0.5, f"Accuracy too low: {ml.accuracy(X, y)}"

    # Test save/load roundtrip
    ml.save("/tmp/test_ml.npz")
    ml2 = TinyML.load("/tmp/test_ml.npz")
    assert ml2.accuracy(X, y) == ml.accuracy(X, y)


def test_studio_engine():
    """Test the 3D studio engine."""
    from core.studio_engine import box, sphere, boolean

    c = box((2, 2, 2))
    s = sphere(0.8, 24, 12)

    assert len(c["verts"]) == 8
    assert len(c["faces"]) == 12
    assert len(s["verts"]) > 0
    assert len(s["faces"]) > 0

    diff = boolean(c, s, "difference", resolution=32)
    assert len(diff["verts"]) > 0
    assert len(diff["faces"]) > 0


def test_boolean_operations():
    """Test boolean operations."""
    from core.studio_engine import box, sphere, boolean

    c = box((2, 2, 2))
    s = sphere(0.8, 16, 8)

    diff = boolean(c, s, "difference", resolution=32)
    uni = boolean(c, s, "union", resolution=32)
    inter = boolean(c, s, "intersect", resolution=32)

    assert len(diff["verts"]) > 0
    assert len(uni["verts"]) > 0
    assert len(inter["verts"]) > 0


def test_scene():
    """Test the Scene class."""
    from core.studio_engine import box, sphere, Scene

    scene = Scene()
    scene.add("cube", box((2, 2, 2)))
    scene.add("sphere", sphere(0.8, 16, 8))

    names = scene.list_names()
    assert "cube" in names
    assert "sphere" in names

    info = scene.info("cube")
    assert info is not None
    assert info["vertices"] == 8
    assert info["faces"] == 12


def test_wake_word_is_optional(monkeypatch):
    """A fresh install reports wake-word unavailability without loading a model."""
    from core.wake_word import is_installed, is_ready

    monkeypatch.setitem(sys.modules, "openwakeword", None)
    assert not is_installed()
    assert not is_ready()


def test_plugin_loader():
    """Test plugin loader discovers plugins."""
    from core.plugin_loader import discover_plugins
    from pathlib import Path

    reg = discover_plugins(Path("plugins"), set())
    assert len(reg._plugins) > 0


def test_action_loader():
    """Test action loader discovers actions."""
    from core.action_loader import discover_actions
    from pathlib import Path

    reg = discover_actions(Path("actions"), set())
    assert len(reg._actions) > 0