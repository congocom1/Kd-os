"""Real-time 3D Arc Reactor widget (QOpenGLWidget).

Renders assets/models/arc_reactor_assembled.obj (exported from the GLB bundle by
scripts/export_reactor_bundle.py) with a pulsing emissive core, slow cinematic spin
and an additive center glow. Theme-aware: call set_palette() to retint.

The mesh is static, so it is compiled into OpenGL display lists once — one
per material group — and only transforms and emission levels animate. That
keeps the model inexpensive to animate on a compatibility-profile context.

Falls back gracefully: if PyOpenGL or the mesh file is missing, the module
still imports and ReactorPanel shows a placeholder instead of GL.
"""
from __future__ import annotations

import json
import logging
import math
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

# Optional gesture control
try:
    from core.gesture_3d import Gesture3DController, GESTURE_3D_AVAILABLE
except Exception:
    GESTURE_3D_AVAILABLE = False
    Gesture3DController = None  # type: ignore


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


MODEL_DIR = _base_dir() / "assets" / "models"
MESH_PATH = MODEL_DIR / "arc_reactor_assembled.obj"
if not MESH_PATH.exists():
    MESH_PATH = MODEL_DIR / "arc_reactor.obj"


def _load_materials(path: Path) -> dict:
    """Read exported base colors/emission; legacy OBJ uses theme colors."""
    try:
        data = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    valid = {}
    for name, material in data.items():
        if not isinstance(material, dict):
            continue
        color = material.get("color", [])
        emission = material.get("emission", [0.0, 0.0, 0.0])
        if not isinstance(color, list) or len(color) not in (3, 4):
            continue
        if not isinstance(emission, list) or len(emission) != 3:
            continue
        if not all(isinstance(v, (int, float)) and math.isfinite(v)
                   for v in color + emission):
            continue
        valid[name] = {"color": color, "emission": emission}
    return valid


def _projection(width: int, height: int, radius: float) -> tuple:
    """Keep the mesh within the clipping planes, including narrow viewports."""
    aspect = max(width, 1) / max(height, 1)
    distance = radius * 3.4 / min(aspect, 1.0)
    return aspect, distance, max(100.0, distance + radius * 4)

try:
    from PyQt6.QtOpenGLWidgets import QOpenGLWidget
    from OpenGL.GL import (
        GL_BLEND, GL_COLOR_BUFFER_BIT, GL_COMPILE, GL_DEPTH_BUFFER_BIT,
        GL_DEPTH_TEST, GL_DIFFUSE, GL_EMISSION, GL_FRONT_AND_BACK, GL_LIGHT0,
        GL_LIGHTING, GL_MODELVIEW, GL_ONE, GL_ONE_MINUS_SRC_ALPHA, GL_POSITION,
        GL_PROJECTION, GL_QUADS, GL_SRC_ALPHA, GL_TRIANGLES, glBegin, glBlendFunc,
        glCallList, glClear, glClearColor, glColor3f, glColor4f, glColorMaterial,
        glDisable, glEnable, glEnd, glEndList, glGenLists, glLightfv, glLoadIdentity,
        glMaterialfv, glMatrixMode, glNewList, glPopMatrix, glPushMatrix,
        glRotatef, glScalef, glTranslatef, glVertex3f, glViewport,
        GL_COLOR_MATERIAL,
    )
    from OpenGL.GLU import gluLookAt, gluPerspective
    OPENGL_AVAILABLE = True
except Exception:  # pragma: no cover - depends on host GL
    OPENGL_AVAILABLE = False
    QOpenGLWidget = None  # type: ignore


def _load_obj(path: Path) -> dict[str, list[tuple]]:
    """Parse the exported OBJ into {material_name: [(v, v, v, normal), ...]}.

    Only triangles (the exporter triangulates). Vertex normals are required;
    falls back to (0,0,1) if a face corner lacks one.
    """
    verts: list[tuple[float, float, float]] = []
    norms: list[tuple[float, float, float]] = []
    groups: dict[str, list[tuple]] = {}
    current = "Base"
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.partition("#")[0].strip()
            if line.startswith("v "):
                _, x, y, z = line.split()[:4]
                verts.append((float(x), float(y), float(z)))
            elif line.startswith("vn "):
                _, x, y, z = line.split()[:4]
                norms.append((float(x), float(y), float(z)))
            elif line.startswith("usemtl "):
                current = line.split(None, 1)[1].strip()
                groups.setdefault(current, [])
            elif line.startswith("f "):
                corners = []
                for tok in line.split()[1:]:
                    parts = tok.split("/")
                    vi = int(parts[0])
                    ni = int(parts[2]) if len(parts) > 2 and parts[2] else 0
                    if vi == 0 or not -len(verts) <= vi <= len(verts):
                        raise ValueError(f"Invalid OBJ vertex index: {vi}")
                    if ni and not -len(norms) <= ni <= len(norms):
                        raise ValueError(f"Invalid OBJ normal index: {ni}")
                    v = verts[vi - 1 if vi > 0 else vi]
                    n = norms[ni - 1 if ni > 0 else ni] if ni else (0.0, 0.0, 1.0)
                    corners.append((v[0], v[1], v[2], n[0], n[1], n[2]))
                if len(corners) >= 3:
                    for i in range(1, len(corners) - 1):
                        groups.setdefault(current, []).extend(
                            (corners[0], corners[i], corners[i + 1]))
    return groups


if OPENGL_AVAILABLE:
    class ReactorGL(QOpenGLWidget):
        """OpenGL viewport rendering the arc reactor model."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self._groups: dict[str, list[tuple]] = {}
            self._lists: dict[str, int] = {}
            self._materials = _load_materials(MESH_PATH)
            self._center = (0.0, 0.0, 0.0)
            self._radius = 1.0
            self._spin = 0.0
            self._yaw = 0.0
            self._pitch = 18.0
            self._zoom = 1.0
            self._pan = [0.0, 0.0]
            self._drag_pos = None
            self._auto_rotate = False
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.setAccessibleName("Interactive reactor model viewer")
            self._pulse = 0.0
            self._power = 1.0           # 0..1 power-on animation
            self._power_target = 1.0
            # Iron-Man defaults: blue-white plasma core, warm metallic housing.
            self._core_rgb = (0.55, 0.85, 1.0)
            self._housing_rgb = (0.72, 0.62, 0.42)
            self._glow_rgb = (0.35, 0.75, 1.0)

            self._timer = QTimer(self)
            self._timer.timeout.connect(self._on_frame)

        # ── public API ────────────────────────────────────────────────────
        def reset_view(self):
            self._yaw, self._pitch, self._spin = 0.0, 18.0, 0.0
            self._zoom = 1.0
            self._pan = [0.0, 0.0]
            self.update()

        def set_auto_rotate(self, enabled: bool):
            self._auto_rotate = bool(enabled)

        def zoom_by(self, steps: float):
            steps = max(-20.0, min(20.0, steps))
            self._zoom = max(0.6, min(4.0, self._zoom * 0.88 ** steps))
            self.update()

        def mousePressEvent(self, event):
            if event.button() in (Qt.MouseButton.LeftButton,
                                  Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
                self._drag_pos = event.position()
                self.setFocus()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
            else:
                super().mousePressEvent(event)

        def mouseMoveEvent(self, event):
            if self._drag_pos is None:
                return
            delta = event.position() - self._drag_pos
            self._drag_pos = event.position()
            if event.buttons() & (Qt.MouseButton.RightButton | Qt.MouseButton.MiddleButton):
                _, distance, _ = _projection(self.width(), self.height(), self._radius)
                scale = 2 * distance * self._zoom * math.tan(math.radians(19)) / max(self.height(), 1)
                self._pan[0] += delta.x() * scale
                self._pan[1] -= delta.y() * scale
            elif event.buttons() & Qt.MouseButton.LeftButton:
                self._yaw = (self._yaw + delta.x() * 0.5) % 360
                self._pitch = (self._pitch + delta.y() * 0.5) % 360
            self.update()
            event.accept()

        def mouseReleaseEvent(self, event):
            self._drag_pos = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()

        def wheelEvent(self, event):
            steps = event.pixelDelta().y() / 40 if not event.pixelDelta().isNull() else event.angleDelta().y() / 120
            self.zoom_by(steps)
            event.accept()

        def mouseDoubleClickEvent(self, event):
            if event.button() == Qt.MouseButton.LeftButton:
                self.reset_view()
                event.accept()
            else:
                super().mouseDoubleClickEvent(event)

        def set_palette(self, core=(0.55, 0.85, 1.0),
                        housing=(0.72, 0.62, 0.42), glow=(0.35, 0.75, 1.0)):
            """Retint core/housing/glow; each an (r,g,b) tuple of 0..1 floats."""
            self._core_rgb = core
            self._housing_rgb = housing
            self._glow_rgb = glow
            self.update()

        def set_power(self, value: float, animate: bool = True):
            """Drive a power-on animation (0 dark → 1 fully lit)."""
            self._power_target = max(0.0, min(1.0, value))
            if not animate:
                self._power = self._power_target
            self.update()

        # ── gesture control ──────────────────────────────────────────────────
        def gesture_rotate(self, dx: float, dy: float):
            """Rotate by gesture delta (degrees)."""
            self._yaw = (self._yaw + dx) % 360
            self._pitch = (self._pitch + dy) % 360
            self.update()

        def gesture_zoom(self, delta: float):
            """Zoom by gesture delta (positive = zoom in)."""
            # Map delta to zoom steps similar to zoom_by
            self._zoom = max(0.6, min(4.0, self._zoom * (0.88 ** delta)))
            self.update()

        def gesture_pan(self, dx: float, dy: float):
            """Pan by gesture delta (normalized screen units)."""
            _, distance, _ = _projection(self.width(), self.height(), self._radius)
            scale = 2 * distance * self._zoom * math.tan(math.radians(19)) / max(self.height(), 1)
            self._pan[0] += dx * scale
            self._pan[1] -= dy * scale
            self.update()

        def gesture_reset(self):
            """Reset view via gesture."""
            self.reset_view()

        # ── lifecycle ─────────────────────────────────────────────────────
        def showEvent(self, event):
            super().showEvent(event)
            if not self._timer.isActive():
                self._timer.start(16)

        def hideEvent(self, event):
            super().hideEvent(event)
            self._timer.stop()
            self._drag_pos = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)

        def _on_frame(self):
            if self._auto_rotate and self._drag_pos is None:
                self._spin = (self._spin + 0.15) % 360.0
            self._pulse += 0.06
            if self._power != self._power_target:
                if self._power_target > self._power:
                    self._power = min(self._power_target, self._power + 0.02)
                else:
                    self._power = max(self._power_target, self._power - 0.05)
            self.update()

        # ── GL ────────────────────────────────────────────────────────────
        def initializeGL(self):
            glClearColor(0.004, 0.008, 0.016, 1.0)
            glEnable(GL_DEPTH_TEST)
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glEnable(GL_LIGHTING)
            glEnable(GL_LIGHT0)
            glEnable(GL_COLOR_MATERIAL)
            glColorMaterial(GL_FRONT_AND_BACK, GL_DIFFUSE)
            glLightfv(GL_LIGHT0, GL_POSITION, (2.0, 3.0, 4.0, 1.0))
            if MESH_PATH.exists():
                try:
                    self._groups = _load_obj(MESH_PATH)
                    self._fit_scale()
                    self._compile_lists()
                except (OSError, ValueError, IndexError):
                    logging.getLogger(__name__).exception("Could not load reactor mesh")

        def _fit_scale(self):
            xs = [c[0] for g in self._groups.values() for c in g]
            ys = [c[1] for g in self._groups.values() for c in g]
            zs = [c[2] for g in self._groups.values() for c in g]
            if not xs:
                return
            self._center = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2,
                            (min(zs) + max(zs)) / 2)
            span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
            self._radius = max(span / 2.0, 1e-6)

        def _compile_lists(self):
            base = glGenLists(len(self._groups))
            for i, (mat, tris) in enumerate(self._groups.items()):
                lst = base + i
                glNewList(lst, GL_COMPILE)
                glBegin(GL_TRIANGLES)
                for vx, vy, vz, nx, ny, nz in tris:
                    from OpenGL.GL import glNormal3f
                    glNormal3f(nx, ny, nz)
                    glVertex3f(vx, vy, vz)
                glEnd()
                glEndList()
                self._lists[mat] = lst

        def paintGL(self):
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            glMatrixMode(GL_PROJECTION)
            glLoadIdentity()
            aspect, d, far = _projection(self.width(), self.height(), self._radius)
            d *= self._zoom
            far = max(far, d + self._radius * 4)
            gluPerspective(38.0, aspect, 0.05, far)
            glMatrixMode(GL_MODELVIEW)
            glLoadIdentity()
            gluLookAt(0, 0, d, 0, 0, 0, 0, 1, 0)

            cx, cy, cz = self._center
            breathe = 0.5 + 0.5 * math.sin(self._pulse)
            glow_level = self._power * (0.72 + 0.28 * breathe)

            glPushMatrix()
            glTranslatef(self._pan[0], self._pan[1], 0)
            # The reactor's face is the XY plane (axis = Z): show it nearly
            # head-on with a slight tilt, and spin around its own axis.
            glRotatef(self._pitch, 1, 0, 0)
            glRotatef(self._yaw, 0, 1, 0)
            glRotatef(self._spin, 0, 0, 1)
            glTranslatef(-cx, -cy, -cz)

            for mat, lst in self._lists.items():
                material = self._materials.get(mat, {})
                emissive = (any(material.get("emission", []))
                            or "emiss" in mat.lower() or "glow" in mat.lower())
                if emissive:
                    r, g, b = self._core_rgb
                    glColor3f(r * glow_level + 0.12, g * glow_level + 0.12,
                              b * glow_level + 0.14)
                    glMaterialfv(GL_FRONT_AND_BACK, GL_EMISSION,
                                 (r * glow_level, g * glow_level,
                                  b * glow_level, 1.0))
                else:
                    r, g, b = material.get("color", self._housing_rgb)[:3]
                    glColor3f(r, g, b)
                    glMaterialfv(GL_FRONT_AND_BACK, GL_EMISSION,
                                 (0.0, 0.0, 0.0, 1.0))
                glCallList(lst)
            glPopMatrix()

            # The old screen-facing glow stayed behind while the model moved.
            # Use the mesh's emissive materials during interactive inspection.

        def _paint_glow(self, level: float):
            """Additive camera-facing quads faking the plasma bloom."""
            if level <= 0.01:
                return
            glDisable(GL_LIGHTING)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE)
            r, g, b = self._glow_rgb
            size = self._radius * (0.9 + 0.15 * math.sin(self._pulse))
            for scale, alpha in ((0.72, 0.10), (0.42, 0.14), (0.20, 0.20)):
                s = size * scale
                glColor4f(r, g, b, alpha * level)
                glBegin(GL_QUADS)
                glVertex3f(-s, -s, 0)
                glVertex3f(s, -s, 0)
                glVertex3f(s, s, 0)
                glVertex3f(-s, s, 0)
                glEnd()
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glEnable(GL_LIGHTING)

        def resizeGL(self, w, h):
            glViewport(0, 0, w, h)


class ReactorPanel(QWidget):
    """Container used by the HUD: GL reactor when possible, placeholder else."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._gesture_controller: Gesture3DController | None = None
        self._gesture_enabled = False

        if OPENGL_AVAILABLE and MESH_PATH.exists():
            self.gl = ReactorGL(self)
            toolbar = QHBoxLayout()
            toolbar.setContentsMargins(8, 6, 8, 6)
            self._rotate_btn = QPushButton("Auto rotate")
            self._rotate_btn.setCheckable(True)
            self._rotate_btn.toggled.connect(self.gl.set_auto_rotate)
            toolbar.addWidget(self._rotate_btn)
            for label, callback in (("−", lambda: self.gl.zoom_by(-1)),
                                    ("+", lambda: self.gl.zoom_by(1)),
                                    ("Reset view", self.gl.reset_view)):
                button = QPushButton(label)
                button.setAccessibleName({"−": "Zoom out", "+": "Zoom in"}.get(label, label))
                button.clicked.connect(callback)
                toolbar.addWidget(button)

            # Gesture control checkbox
            if GESTURE_3D_AVAILABLE:
                self._gesture_cb = QCheckBox("Gesture control")
                self._gesture_cb.setToolTip(
                    "Control the reactor with hand gestures via webcam:\n"
                    "• One hand (pointing): Rotate\n"
                    "• Two hands (pinch): Zoom\n"
                    "• Two hands (open palms): Pan\n"
                    "• Fist: Reset view"
                )
                self._gesture_cb.toggled.connect(self._toggle_gesture_control)
                toolbar.addWidget(self._gesture_cb)

            toolbar.addStretch()
            layout.addLayout(toolbar)
            layout.addWidget(self.gl, stretch=1)

            help_lines = ["Drag: 360° orbit  ·  Right-drag: pan  ·  Scroll: zoom  ·  Double-click: reset"]
            if GESTURE_3D_AVAILABLE:
                help_lines.append("Gestures: Point to rotate  ·  Pinch to zoom  ·  Open palms to pan  ·  Fist to reset")
            help_text = QLabel("  ·  ".join(help_lines))
            help_text.setWordWrap(True)
            help_text.setContentsMargins(10, 4, 10, 8)
            layout.addWidget(help_text)
        else:
            self.gl = None
            reason = "PyOpenGL not installed" if not OPENGL_AVAILABLE \
                else f"reactor mesh missing: {MESH_PATH}"
            label = QLabel(f"⬢ ARC REACTOR\n({reason})", self)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color: #6fb7d9; background: #02060a;")
            layout.addWidget(label)

    def _toggle_gesture_control(self, enabled: bool):
        if not GESTURE_3D_AVAILABLE or self.gl is None:
            if hasattr(self, "_gesture_cb"):
                self._gesture_cb.setChecked(False)
            return

        if enabled:
            try:
                self._gesture_controller = Gesture3DController()
                self._gesture_controller.on_rotate = self.gl.gesture_rotate
                self._gesture_controller.on_zoom = self.gl.gesture_zoom
                self._gesture_controller.on_pan = self.gl.gesture_pan
                self._gesture_controller.on_reset = self.gl.gesture_reset
                self._gesture_controller.enable(True)
                self._gesture_enabled = True
            except Exception as e:
                logging.getLogger(__name__).warning(f"Failed to start gesture control: {e}")
                if hasattr(self, "_gesture_cb"):
                    self._gesture_cb.setChecked(False)
        else:
            if self._gesture_controller:
                self._gesture_controller.enable(False)
                self._gesture_controller = None
            self._gesture_enabled = False

    def closeEvent(self, event):
        """Clean up gesture controller on close."""
        if self._gesture_controller:
            self._gesture_controller.enable(False)
        super().closeEvent(event)

    def set_palette(self, **colors):
        if self.gl is not None:
            self.gl.set_palette(**colors)

    def apply_theme(self, palette: dict):
        """Retint from a cinematic_theme palette dict (hex strings)."""
        def _rgb(key: str, default: tuple) -> tuple:
            h = palette.get(key, "")
            if isinstance(h, str) and h.startswith("#") and len(h) == 7:
                try:
                    return (int(h[1:3], 16) / 255, int(h[3:5], 16) / 255,
                            int(h[5:7], 16) / 255)
                except ValueError:
                    pass
            return default
        self.set_palette(
            core=_rgb("reactor_core", (0.55, 0.85, 1.0)),
            housing=_rgb("reactor_housing", (0.72, 0.62, 0.42)),
            glow=_rgb("holo", (0.35, 0.75, 1.0)),
        )

    def set_power(self, value: float, animate: bool = True):
        if self.gl is not None:
            self.gl.set_power(value, animate)
