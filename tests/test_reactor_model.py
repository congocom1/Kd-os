"""Validate the bundled reactor without creating an OpenGL context."""
from types import SimpleNamespace
import json

import numpy as np
import pytest

from core import reactor_widget
from core.reactor_widget import MESH_PATH, _load_materials, _load_obj


def test_assembled_reactor_geometry_and_materials():
    assert MESH_PATH.name == "arc_reactor_assembled.obj"
    groups = _load_obj(MESH_PATH)
    materials = _load_materials(MESH_PATH)
    assert groups
    assert set(groups) <= set(materials)
    vertices = np.array([v for group in groups.values() for v in group])
    assert vertices.shape[1] == 6
    assert len(vertices) % 3 == 0
    assert np.isfinite(vertices).all()
    # Export is centered, with the reactor face in the XY plane.
    spans = np.ptp(vertices[:, :3], axis=0)
    assert spans[2] < min(spans[:2])
    assert np.max(np.abs(vertices[:, :3])) < 2


def test_legacy_material_fallback(tmp_path):
    assert _load_materials(tmp_path / "legacy.obj") == {}
    (tmp_path / "legacy.json").write_text("not json")
    assert _load_materials(tmp_path / "legacy.obj") == {}


@pytest.mark.skipif(not reactor_widget.OPENGL_AVAILABLE, reason="OpenGL unavailable")
@pytest.mark.parametrize("start,target", [(0.0, 0.33), (1.0, 0.33), (0.4, 0.4)])
def test_power_animation_settles_without_oscillation(start, target):
    state = SimpleNamespace(_spin=0.0, _pulse=0.0, _power=start,
                            _power_target=target, _auto_rotate=False,
                            _drag_pos=None, update=lambda: None)
    for _ in range(100):
        reactor_widget.ReactorGL._on_frame(state)
    assert state._power == target
    reactor_widget.ReactorGL._on_frame(state)
    assert state._power == target


@pytest.mark.parametrize("payload", [None, [], 1, {"bad": None},
    {"bad": {"color": [1, 2]}}, {"bad": {"color": [1, 2, "x"]}},
    {"bad": {"color": [1, 2, float("nan")]}}])
def test_invalid_material_data_is_ignored(tmp_path, payload):
    (tmp_path / "model.json").write_text(json.dumps(payload))
    assert _load_materials(tmp_path / "model.obj") == {}


def test_obj_relative_indices_and_comments(tmp_path):
    model = tmp_path / "model.obj"
    model.write_text("  v 0 0 0\nv 1 0 0\nv 0 1 0\n"
                     "vn 0 1 0\nf -3//-1 -2//-1 -1//-1 # triangle\n")
    vertices = _load_obj(model)["Base"]
    assert len(vertices) == 3
    assert all(v[3:] == (0, 1, 0) for v in vertices)


@pytest.mark.parametrize("index", [0, 4, -4])
def test_invalid_obj_indices_rejected(tmp_path, index):
    model = tmp_path / "model.obj"
    model.write_text(f"v 0 0 0\nv 1 0 0\nv 0 1 0\nf {index} 2 3\n")
    with pytest.raises(ValueError, match="vertex index"):
        _load_obj(model)


@pytest.mark.parametrize("size", [(0, 0), (1, 1000), (660, 580)])
def test_projection_contains_model(size):
    aspect, distance, far = reactor_widget._projection(*size, 10)
    assert aspect > 0
    assert distance > 10
    assert far > distance + 10


def test_invalid_theme_color_uses_default():
    colors = {}
    panel = SimpleNamespace(set_palette=lambda **kwargs: colors.update(kwargs))
    reactor_widget.ReactorPanel.apply_theme(panel, {"reactor_core": "#GGGGGG"})
    assert colors["core"] == (0.55, 0.85, 1.0)


@pytest.mark.skipif(not reactor_widget.OPENGL_AVAILABLE, reason="OpenGL unavailable")
def test_viewer_zoom_limits_and_reset():
    state = SimpleNamespace(_zoom=1.0, update=lambda: None)
    reactor_widget.ReactorGL.zoom_by(state, 1000)
    assert state._zoom == 0.6
    reactor_widget.ReactorGL.zoom_by(state, -1000)
    assert state._zoom == 4.0
    reactor_widget.ReactorGL.reset_view(state)
    assert (state._yaw, state._pitch, state._spin, state._zoom) == (0, 18, 0, 1)
    assert state._pan == [0, 0]


@pytest.mark.skipif(not reactor_widget.OPENGL_AVAILABLE, reason="OpenGL unavailable")
@pytest.mark.parametrize("enabled,dragging,expected", [
    (False, False, 0), (True, False, 0.15), (True, True, 0),
])
def test_auto_rotation_pauses_during_drag(enabled, dragging, expected):
    state = SimpleNamespace(_spin=0.0, _pulse=0.0, _power=1,
                            _power_target=1, _auto_rotate=enabled,
                            _drag_pos=object() if dragging else None,
                            update=lambda: None)
    reactor_widget.ReactorGL._on_frame(state)
    assert state._spin == expected


@pytest.mark.skipif(not reactor_widget.OPENGL_AVAILABLE, reason="OpenGL unavailable")
def test_mouse_drag_orbits_and_pans():
    from PyQt6.QtCore import QPointF, Qt

    state = SimpleNamespace(_drag_pos=QPointF(0, 0), _yaw=0, _pitch=18,
                            _radius=1, _zoom=1, _pan=[0, 0],
                            width=lambda: 660, height=lambda: 580,
                            update=lambda: None)
    event = SimpleNamespace(position=lambda: QPointF(20, 10),
                            buttons=lambda: Qt.MouseButton.LeftButton,
                            accept=lambda: None)
    reactor_widget.ReactorGL.mouseMoveEvent(state, event)
    assert (state._yaw, state._pitch) == (10, 23)
    event.position = lambda: QPointF(40, 20)
    event.buttons = lambda: Qt.MouseButton.RightButton
    reactor_widget.ReactorGL.mouseMoveEvent(state, event)
    assert state._pan[0] > 0 and state._pan[1] < 0


@pytest.mark.skipif(not reactor_widget.OPENGL_AVAILABLE, reason="OpenGL unavailable")
@pytest.mark.parametrize("dx,dy,expected", [
    (0, 360, (0, 198)),
    (360, 0, (180, 18)),
    (720, 720, (0, 18)),
    (-720, -720, (0, 18)),
    (-180, -180, (270, 288)),
    (2160, 2160, (0, 18)),
])
def test_full_360_orbit(dx, dy, expected):
    from PyQt6.QtCore import QPointF, Qt

    state = SimpleNamespace(_drag_pos=QPointF(0, 0), _yaw=0, _pitch=18,
                            update=lambda: None)
    event = SimpleNamespace(position=lambda: QPointF(dx, dy),
                            buttons=lambda: Qt.MouseButton.LeftButton,
                            accept=lambda: None)
    reactor_widget.ReactorGL.mouseMoveEvent(state, event)
    assert (state._yaw, state._pitch) == expected