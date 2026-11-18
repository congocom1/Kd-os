"""
core/visual_display.py — Visual Display Engine for JARVIS 3D Studio

Provides a PyQt6 OpenGL-based 3D viewer for studio_modeler meshes.

Features:
- Real-time 3D mesh rendering using OpenGL
- Orbit camera controls (mouse drag to rotate, wheel to zoom)
- Wireframe/solid shading modes
- Multiple mesh support with per-object colors
- Integration with core.studio_engine.Scene
- HUD panel embedding

Usage:
    from core.visual_display import VisualDisplayWidget
    from PyQt6.QtWidgets import QMainWindow, QVBoxLayout, QWidget

    widget = VisualDisplayWidget()
    widget.load_scene(my_scene)  # Load meshes from studio_engine.Scene
"""

from __future__ import annotations

import math
import random
from typing import Dict

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QComboBox, QLabel, QPushButton, QVBoxLayout, QWidget

try:
    from PyQt6.QtOpenGLWidgets import QOpenGLWidget
    from OpenGL.GL import (
        GL_BLEND, GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_DEPTH_TEST,
        GL_FILL, GL_FRONT_AND_BACK, GL_LINE, GL_LINES, GL_MODELVIEW,
        GL_ONE_MINUS_SRC_ALPHA, GL_POLYGON_OFFSET_LINE, GL_PROJECTION,
        GL_SRC_ALPHA, GL_TRIANGLES, glBegin, glBlendFunc, glClear, glClearColor,
        glColor4f, glDisable, glEnable, glEnd, glLineWidth,
        glLoadIdentity, glMatrixMode, glPolygonMode, glPolygonOffset,
        glVertex3f, glTranslatef, glViewport,
    )
    from OpenGL.GLU import gluLookAt, gluPerspective
    OPENGL_AVAILABLE = True
except Exception:
    OPENGL_AVAILABLE = False
    QOpenGLWidget = None  # type: ignore


if OPENGL_AVAILABLE:
    class MeshRenderer(QOpenGLWidget):
        """Holographic OpenGL viewport for 3D studio meshes."""

        # Cinematic Tron-style palette
        _GRID_COLOR = (0.0, 0.82, 0.94, 0.22)      # cyan grid
        _MESH_FILL = (0.0, 0.72, 0.85, 0.18)       # translucent cyan solid
        _MESH_EDGE = (0.0, 0.9, 1.0, 0.75)         # bright cyan wireframe
        _SELECTED_FILL = (1.0, 0.65, 0.0, 0.22)    # amber translucent
        _SELECTED_EDGE = (1.0, 0.85, 0.2, 0.85)    # bright amber
        _SCAN_COLOR = (0.0, 0.9, 1.0, 0.12)        # sweeping scan plane

        def __init__(self, parent=None):
            super().__init__(parent)
            self._meshes: Dict[str, dict] = {}
            self._camera_angle_x = 0.25
            self._camera_angle_y = 0.0
            self._camera_distance = 5.0
            self._camera_pan = [0.0, 0.0]
            self._last_pos = None
            self._wireframe_mode = False
            self._selected_mesh = None
            self._tick = 0
            self._auto_rotate = True
            self._particles = [
                (
                    random.uniform(-2.5, 2.5),
                    random.uniform(-1.0, 2.0),
                    random.uniform(-2.5, 2.5),
                    random.uniform(0.2, 1.0),   # speed
                )
                for _ in range(28)
            ]

            # Animation timer (~60 FPS) — runs only while the widget is visible.
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._on_frame)

        def showEvent(self, event):
            super().showEvent(event)
            if not self._timer.isActive():
                self._timer.start(16)

        def hideEvent(self, event):
            super().hideEvent(event)
            self._timer.stop()

        def _on_frame(self):
            """Advance holographic animation."""
            self._tick += 1
            if self._auto_rotate and self._meshes:
                self._camera_angle_y += 0.003
            self.update()

        def initializeGL(self):
            """Initialize OpenGL context."""
            glClearColor(0.0, 0.03, 0.05, 1.0)
            glEnable(GL_DEPTH_TEST)
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        def paintGL(self):
            """Render holographic scene."""
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

            # Projection
            glMatrixMode(GL_PROJECTION)
            glLoadIdentity()
            aspect = self.width() / max(self.height(), 1)
            gluPerspective(45.0, aspect, 0.1, 100.0)

            # Modelview
            glMatrixMode(GL_MODELVIEW)
            glLoadIdentity()

            # Orbit camera
            gluLookAt(
                self._camera_distance * math.sin(self._camera_angle_y) * math.cos(self._camera_angle_x),
                self._camera_distance * math.sin(self._camera_angle_x),
                self._camera_distance * math.cos(self._camera_angle_y) * math.cos(self._camera_angle_x),
                0, 0, 0,
                0, 1, 0,
            )

            glTranslatef(self._camera_pan[0], self._camera_pan[1], 0.0)
            self._draw_grid()
            self._draw_particles()
            self._draw_scan_plane()

            # Render meshes with holographic overlay
            for name, mesh in self._meshes.items():
                selected = name == self._selected_mesh
                self._render_mesh(mesh, selected)
                if selected:
                    self._draw_bounds_cage(mesh)
                    self._draw_selection_pulse(mesh)

        def _draw_grid(self):
            """Draw a depth-fading holographic floor grid."""
            size = 6
            step = 0.5
            glDisable(GL_DEPTH_TEST)
            glLineWidth(1.0)
            glBegin(GL_LINES)
            for i in range(-size, size + 1):
                x = i * step
                # Fade outer lines for a soft horizon effect.
                fade = max(0.0, 1.0 - abs(x) / (size * step))
                alpha = self._GRID_COLOR[3] * (0.3 + 0.7 * fade)
                glColor4f(self._GRID_COLOR[0], self._GRID_COLOR[1],
                          self._GRID_COLOR[2], alpha)
                glVertex3f(x, -1.5, -size * step)
                glVertex3f(x, -1.5, size * step)
                glVertex3f(-size * step, -1.5, x)
                glVertex3f(size * step, -1.5, x)
            glEnd()
            glEnable(GL_DEPTH_TEST)

        def _draw_scan_plane(self):
            """Draw a slow vertical scan plane sweeping through the workspace."""
            t = (self._tick % 400) / 400.0
            x = -3.0 + t * 6.0
            glDisable(GL_DEPTH_TEST)
            glColor4f(*self._SCAN_COLOR)
            glBegin(GL_TRIANGLES)
            glVertex3f(x, -1.5, -3.0)
            glVertex3f(x, 2.5, -3.0)
            glVertex3f(x, 2.5, 3.0)
            glVertex3f(x, -1.5, -3.0)
            glVertex3f(x, 2.5, 3.0)
            glVertex3f(x, -1.5, 3.0)
            glEnd()
            glEnable(GL_DEPTH_TEST)

        def _draw_particles(self):
            """Floating dust motes to sell the holographic volume."""
            glDisable(GL_DEPTH_TEST)
            glLineWidth(1.0)
            t = self._tick * 0.016
            for x0, y0, z0, speed in self._particles:
                # Slow upward drift with wrapping and a gentle sine sway.
                y = ((y0 + t * speed * 0.35 + 1.0) % 3.0) - 1.0
                x = x0 + 0.15 * math.sin(t * speed + y0)
                z = z0 + 0.15 * math.cos(t * speed * 0.8 + x0)
                alpha = 0.10 + 0.15 * (0.5 + 0.5 * math.sin(t * 2.0 * speed))
                glColor4f(0.0, 0.85, 1.0, alpha)
                glBegin(GL_LINES)
                glVertex3f(x, y, z)
                glVertex3f(x + 0.015, y + 0.015, z)
                glEnd()
            glEnable(GL_DEPTH_TEST)

        def _mesh_bounds(self, mesh: dict):
            """Return (min_x, min_y, min_z, max_x, max_y, max_z) or None."""
            vertices = mesh.get("vertices", [])
            if len(vertices) == 0:
                return None
            xs = [v[0] for v in vertices]
            ys = [v[1] for v in vertices]
            zs = [v[2] for v in vertices]
            return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))

        def _draw_bounds_cage(self, mesh: dict):
            """Draw holographic corner brackets around the selected mesh."""
            b = self._mesh_bounds(mesh)
            if b is None:
                return
            x0, y0, z0, x1, y1, z1 = b
            pad = 0.06
            x0 -= pad; y0 -= pad; z0 -= pad
            x1 += pad; y1 += pad; z1 += pad
            size = min(x1 - x0, y1 - y0, z1 - z0) * 0.25

            corners = [
                (x0, y0, z0, +1, +1, +1),
                (x1, y0, z0, -1, +1, +1),
                (x1, y0, z1, -1, +1, -1),
                (x0, y0, z1, +1, +1, -1),
                (x0, y1, z0, +1, -1, +1),
                (x1, y1, z0, -1, -1, +1),
                (x1, y1, z1, -1, -1, -1),
                (x0, y1, z1, +1, -1, -1),
            ]

            glDisable(GL_DEPTH_TEST)
            glLineWidth(2.0)
            pulse = 0.6 + 0.4 * math.sin(self._tick * 0.08)
            glColor4f(1.0, 0.85, 0.2, 0.75 * pulse)
            glBegin(GL_LINES)
            for cx, cy, cz, dx, dy, dz in corners:
                # Three short bracket edges per corner.
                glVertex3f(cx, cy, cz)
                glVertex3f(cx + dx * size, cy, cz)
                glVertex3f(cx, cy, cz)
                glVertex3f(cx, cy + dy * size, cz)
                glVertex3f(cx, cy, cz)
                glVertex3f(cx, cy, cz + dz * size)
            glEnd()
            glEnable(GL_DEPTH_TEST)

        def _draw_selection_pulse(self, mesh: dict):
            """Expanding holographic ring beneath the selected mesh."""
            b = self._mesh_bounds(mesh)
            if b is None:
                return
            x0, y0, z0, x1, y1, z1 = b
            cx = (x0 + x1) * 0.5
            cz = (z0 + z1) * 0.5
            radius = max(x1 - x0, z1 - z0) * 0.75 + 0.15

            t = (self._tick % 60) / 60.0
            r = radius * (0.6 + t * 0.8)
            alpha = (1.0 - t) * 0.45

            glDisable(GL_DEPTH_TEST)
            glLineWidth(1.5)
            glColor4f(1.0, 0.85, 0.2, alpha)
            glBegin(GL_LINES)
            segments = 48
            for i in range(segments):
                a0 = (i / segments) * 2.0 * math.pi
                a1 = ((i + 1) / segments) * 2.0 * math.pi
                glVertex3f(cx + math.cos(a0) * r, y0 - 0.08, cz + math.sin(a0) * r)
                glVertex3f(cx + math.cos(a1) * r, y0 - 0.08, cz + math.sin(a1) * r)
            glEnd()
            glEnable(GL_DEPTH_TEST)

        def _render_mesh(self, mesh: dict, selected: bool):
            """Render a single mesh with holographic solid + wireframe overlay."""
            vertices = mesh.get("vertices", [])
            faces = mesh.get("faces", [])

            if len(vertices) == 0 or len(faces) == 0:
                return

            if selected:
                fill_color = self._SELECTED_FILL
                edge_color = self._SELECTED_EDGE
            else:
                fill_color = self._MESH_FILL
                edge_color = self._MESH_EDGE

            # Solid holographic fill
            if not self._wireframe_mode:
                glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
                glColor4f(*fill_color)
                self._draw_triangles(vertices, faces)

            # Bright wireframe overlay
            glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
            glEnable(GL_POLYGON_OFFSET_LINE)
            glPolygonOffset(-1.0, -1.0)
            glLineWidth(1.5 if selected else 1.0)
            glColor4f(*edge_color)
            self._draw_triangles(vertices, faces)
            glDisable(GL_POLYGON_OFFSET_LINE)

            # Restore fill mode for subsequent grid-less draws
            glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)

        def _draw_triangles(self, vertices, faces):
            """Emit triangle geometry from vertices and faces."""
            glBegin(GL_TRIANGLES)
            for face in faces:
                for idx in face:
                    if idx < len(vertices):
                        v = vertices[idx]
                        glVertex3f(v[0], v[1], v[2])
            glEnd()

        def resizeGL(self, w, h):
            """Handle resize."""
            glViewport(0, 0, w, h)

        def mousePressEvent(self, event):
            """Start camera manipulation."""
            self._last_pos = event.pos()
            self._auto_rotate = False

        def mouseMoveEvent(self, event):
            """Rotate camera."""
            if self._last_pos is None:
                return

            delta = event.pos() - self._last_pos
            self._camera_angle_x += delta.y() * 0.01
            self._camera_angle_y += delta.x() * 0.01
            self._last_pos = event.pos()
            self.update()

        def wheelEvent(self, event):
            """Zoom camera."""
            delta = event.angleDelta().y()
            self._camera_distance = max(1.0, min(20.0, self._camera_distance - delta * 0.01))
            self.update()

        def gesture_rotate(self, dx: float, dy: float):
            self._auto_rotate = False
            self._camera_angle_y += math.radians(dx)
            self._camera_angle_x = max(-1.5, min(1.5, self._camera_angle_x + math.radians(dy)))
            self.update()

        def gesture_zoom(self, delta: float):
            self._camera_distance = max(1.0, min(20.0, self._camera_distance - delta))
            self.update()

        def gesture_pan(self, dx: float, dy: float):
            self._camera_pan[0] += dx
            self._camera_pan[1] += dy
            self.update()

        def gesture_reset(self):
            self._camera_angle_x, self._camera_angle_y = 0.25, 0.0
            self._camera_distance = 5.0
            self._camera_pan = [0.0, 0.0]
            self.update()

        def load_meshes(self, meshes: Dict[str, dict]):
            """Load meshes for rendering."""
            self._meshes = meshes
            self.update()

        def clear(self):
            """Clear all meshes."""
            self._meshes = {}
            self.update()

        def set_wireframe(self, enabled: bool):
            """Toggle wireframe mode."""
            self._wireframe_mode = enabled
            self.update()

        def select_mesh(self, name: str):
            """Select a mesh for highlighting."""
            self._selected_mesh = name
            self.update()

        def set_auto_rotate(self, enabled: bool):
            """Enable/disable idle turntable rotation."""
            self._auto_rotate = enabled
            self.update()


class VisualDisplayWidget(QWidget):
    """High-level widget for 3D visual display with controls."""

    def __init__(self, parent=None, accent_color: str = "#00e5ff"):
        super().__init__(parent)
        self._studio_scene = None
        self._accent_color = accent_color
        self._setup_ui()

    def _setup_ui(self):
        """Setup the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Controls bar
        controls = QWidget()
        controls.setStyleSheet(f"""
            QWidget {{
                background: rgba(0, 7, 10, 200);
                border: 1px solid {self._accent_color}44;
                border-radius: 4px;
            }}
        """)
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(6, 6, 6, 6)
        controls_layout.setSpacing(4)

        # Mesh selector
        self._mesh_selector = QComboBox()
        self._mesh_selector.setEnabled(False)
        self._mesh_selector.currentTextChanged.connect(self._on_mesh_selected)
        self._mesh_selector.setStyleSheet(f"""
            QComboBox {{
                background: rgba(0, 14, 22, 220);
                color: #e0f7ff;
                border: 1px solid {self._accent_color}66;
                border-radius: 3px;
                padding: 3px 6px;
                font-family: 'Courier New', monospace;
                font-size: 8pt;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background: #00070a;
                color: #e0f7ff;
                border: 1px solid {self._accent_color}66;
                selection-background-color: {self._accent_color}44;
            }}
        """)
        controls_layout.addWidget(self._mesh_selector)

        # Wireframe toggle
        self._wireframe_btn = QPushButton("Wireframe: OFF")
        self._wireframe_btn.setCheckable(True)
        self._wireframe_btn.setFont(QFont("Courier New", 7))
        self._wireframe_btn.clicked.connect(self._on_wireframe_toggle)
        self._wireframe_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(0, 14, 22, 220);
                color: {self._accent_color};
                border: 1px solid {self._accent_color}66;
                border-radius: 3px;
                padding: 4px 8px;
                font-family: 'Courier New', monospace;
                font-size: 8pt;
            }}
            QPushButton:checked {{
                background: {self._accent_color}33;
                border: 1px solid {self._accent_color};
            }}
            QPushButton:hover {{
                background: {self._accent_color}22;
                border: 1px solid {self._accent_color};
            }}
        """)
        controls_layout.addWidget(self._wireframe_btn)

        # Auto-rotate toggle
        self._rotate_btn = QPushButton("Turntable: ON")
        self._rotate_btn.setCheckable(True)
        self._rotate_btn.setChecked(True)
        self._rotate_btn.setFont(QFont("Courier New", 7))
        self._rotate_btn.clicked.connect(self._on_rotate_toggle)
        self._rotate_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(0, 14, 22, 220);
                color: {self._accent_color};
                border: 1px solid {self._accent_color}66;
                border-radius: 3px;
                padding: 4px 8px;
                font-family: 'Courier New', monospace;
                font-size: 8pt;
            }}
            QPushButton:checked {{
                background: {self._accent_color}33;
                border: 1px solid {self._accent_color};
            }}
            QPushButton:hover {{
                background: {self._accent_color}22;
                border: 1px solid {self._accent_color};
            }}
        """)
        controls_layout.addWidget(self._rotate_btn)

        layout.addWidget(controls)

        # 3D View
        if OPENGL_AVAILABLE:
            self._gl_widget = MeshRenderer()
            self._gl_widget.setStyleSheet(f"""
                QOpenGLWidget {{
                    border: 1px solid {self._accent_color}66;
                    border-radius: 4px;
                }}
            """)
        else:
            self._gl_widget = QLabel(
                "HOLOGRAPHIC WORKSPACE\n[OpenGL unavailable]\n\n"
                "3D preview disabled in this environment"
            )
            self._gl_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._gl_widget.setFont(QFont("Courier New", 8))
            self._gl_widget.setStyleSheet(f"""
                QLabel {{
                    color: {self._accent_color};
                    background: qradialgradient(
                        cx: 0.5, cy: 0.5, radius: 0.7,
                        stop: 0 rgba(0, 20, 35, 180),
                        stop: 1 rgba(0, 4, 8, 220)
                    );
                    border: 1px solid {self._accent_color}44;
                    border-radius: 4px;
                    padding: 20px;
                }}
            """)
        layout.addWidget(self._gl_widget, stretch=1)

    def load_scene(self, scene):
        """Load a studio scene for display."""
        try:
            from core.studio_engine import Scene
            if not isinstance(scene, Scene):
                return

            meshes = {}
            for name, mesh in scene.objects.items():
                if hasattr(mesh, "vertices"):
                    verts = mesh.vertices
                    faces = mesh.faces
                else:
                    verts = mesh.get("verts", mesh.get("vertices", []))
                    faces = mesh.get("faces", [])
                meshes[name] = {
                    "vertices": verts,
                    "faces": faces,
                }

            self._studio_scene = scene
            if OPENGL_AVAILABLE and hasattr(self._gl_widget, "load_meshes"):
                self._gl_widget.load_meshes(meshes)
            self._update_mesh_selector(meshes.keys())

        except Exception as e:
            print(f"[Visual Display] Error loading scene: {e}")

    def _update_mesh_selector(self, mesh_names):
        """Update the mesh selector dropdown."""
        self._mesh_selector.clear()
        self._mesh_selector.addItems(list(mesh_names))
        self._mesh_selector.setEnabled(len(mesh_names) > 0)

    def _on_mesh_selected(self, name):
        """Handle mesh selection."""
        if OPENGL_AVAILABLE and hasattr(self._gl_widget, "select_mesh"):
            self._gl_widget.select_mesh(name)

    def _on_wireframe_toggle(self, checked):
        """Handle wireframe toggle."""
        self._wireframe_btn.setText(f"Wireframe: {'ON' if checked else 'OFF'}")
        if OPENGL_AVAILABLE and hasattr(self._gl_widget, "set_wireframe"):
            self._gl_widget.set_wireframe(checked)

    def _on_rotate_toggle(self, checked):
        """Handle turntable auto-rotate toggle."""
        self._rotate_btn.setText(f"Turntable: {'ON' if checked else 'OFF'}")
        if OPENGL_AVAILABLE and hasattr(self._gl_widget, "set_auto_rotate"):
            self._gl_widget.set_auto_rotate(checked)

    def clear(self):
        """Clear the display."""
        if OPENGL_AVAILABLE and hasattr(self._gl_widget, "clear"):
            self._gl_widget.clear()
        self._mesh_selector.clear()
        self._mesh_selector.setEnabled(False)
        self._studio_scene = None


# Convenience function for HUD integration
def create_visual_display(parent=None):
    """Create a visual display widget for embedding in HUD."""
    return VisualDisplayWidget(parent)
