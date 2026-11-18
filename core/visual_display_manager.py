"""
core/visual_display_manager.py — Visual Display Manager for JARVIS

Central visual display controller for 3D models, HUD overlays, and visual outputs.
Integrates with core.visual_display, plugins.studio_modeler, and core.studio_engine.

Provides:
- 3D model visualization
- HUD visual panels
- Image display
- Video display integration
"""

from __future__ import annotations

import os
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger("jarvis.visual_display")

# Optional imports for PyQt
try:
    from PyQt6.QtWidgets import QApplication
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


if QT_AVAILABLE:
    from PyQt6.QtCore import QObject, QThread, pyqtSignal

    class _SceneBridge(QObject):
        """Thread bridge: plugins run on worker threads, widgets live on the
        GUI thread. Emitting a queued signal is thread-safe; touching a QWidget
        from a worker thread is not."""
        load_requested = pyqtSignal(object)  # carries a studio Scene

else:
    QObject = None  # type: ignore


@dataclass
class VisualDisplayConfig:
    """Configuration for visual display."""
    enabled: bool = os.getenv("VISUAL_DISPLAY_ENABLED", "true").lower() in ("1", "true", "yes")
    default_view: str = "3d_studio"
    auto_refresh_ms: int = 100
    show_wireframe: bool = False
    show_axes: bool = True
    background_color: str = "#00070a"


class VisualDisplayManager:
    """Manages visual display across JARVIS."""

    def __init__(self, config: Optional[VisualDisplayConfig] = None):
        self.config = config or VisualDisplayConfig()
        self._current_view = self.config.default_view
        self._studio_scene = None
        self._widgets: Dict[str, Any] = {}
        self._visual_data: Dict[str, Any] = {}
        self._bridge = None

    def get_scene(self):
        """The single studio scene, shared by manager and studio plugins."""
        if self._studio_scene is None:
            try:
                from core.studio_engine import Scene
                self._studio_scene = Scene()
            except Exception as e:
                logger.warning(f"[Visual Display] Could not load studio scene: {e}")
        return self._studio_scene

    def _on_gui_thread(self) -> bool:
        app = QApplication.instance()
        return app is not None and app.thread() == QThread.currentThread()

    def _gui_load_scene(self, scene):
        """Load a scene into the registered widget — GUI thread only."""
        widget = self._widgets.get("3d_studio")
        if widget is not None and scene is not None:
            try:
                widget.load_scene(scene)
            except Exception as e:
                logger.error(f"[Visual Display] Scene load failed: {e}")

    def _push_scene(self):
        """Push the shared scene to the widget, marshaling to the GUI thread."""
        scene = self._studio_scene
        if scene is None or "3d_studio" not in self._widgets:
            return
        if self._on_gui_thread():
            self._gui_load_scene(scene)
            return
        if self._bridge is None:
            self._bridge = _SceneBridge()
            self._bridge.load_requested.connect(self._gui_load_scene)
        self._bridge.load_requested.emit(scene)

    def initialize(self):
        """Initialize the visual display system."""
        logger.info(f"[Visual Display] Initializing with view: {self._current_view}")
        self.get_scene()
        return True

    def set_widget(self, view_name: str, widget) -> bool:
        """Register an externally-created widget for a view.

        The HUD embeds its own VisualDisplayWidget and registers it here so
        that global studio actions render into the embedded panel instead of
        spawning a separate surface."""
        self._widgets[view_name] = widget
        logger.info(f"[Visual Display] Widget registered for view: {view_name}")
        return True

    def _ensure_widget(self):
        """Lazily create the 3D visual widget when first needed.

        Creating a QWidget without a QApplication or X11 display aborts the
        process, so we never build it during import or initialize()."""
        if not QT_AVAILABLE:
            logger.warning("[Visual Display] Qt not available, visual display disabled")
            return None
        if "3d_studio" in self._widgets:
            return self._widgets["3d_studio"]

        # A QWidget without a QApplication aborts the interpreter. Only build
        # the visual surface when the main app has already created one.
        if QApplication.instance() is None:
            logger.debug("[Visual Display] No QApplication yet; deferring widget creation")
            return None

        try:
            from core.visual_display import VisualDisplayWidget
            widget = VisualDisplayWidget()
            self._widgets["3d_studio"] = widget
            logger.info("[Visual Display] 3D Studio widget initialized")
            return widget
        except Exception as e:
            logger.warning(f"[Visual Display] Could not initialize 3D widget: {e}")
            return None

    def show_3d_model(self, name: str, mesh_data: Optional[Dict] = None):
        """Display a 3D model in the visual display."""
        if not self.config.enabled:
            return False

        widget = self._ensure_widget()
        if widget is None:
            return False

        try:
            # Load mesh into the shared studio scene if not already there
            if mesh_data:
                scene = self.get_scene()
                if scene is not None:
                    mesh_obj = {
                        "verts": mesh_data.get("vertices", mesh_data.get("verts", [])),
                        "faces": mesh_data.get("faces", []),
                    }
                    scene.add(name, mesh_obj)

            # Update display (thread-marshaled to the GUI thread)
            self._push_scene()
            self.set_current_view("3d_studio")
            logger.info(f"[Visual Display] Showing 3D model: {name}")
            return True

        except Exception as e:
            logger.error(f"[Visual Display] Error showing 3D model: {e}")

        return False

    def sample_model_surface(self, mesh_data: Dict, num_samples: int = 1000,
                             backend: str = 'compat', device: str = 'cpu'):
        """Sample a workshop mesh using an explicitly selected geometry backend.

        This is geometry processing, not a replacement for the OpenGL renderer.
        Dependency failures are actionable exceptions rather than silent fallback.
        """
        from core.geometry_backend import sample_mesh
        return sample_mesh(mesh_data.get('vertices', mesh_data.get('verts', [])),
                           mesh_data.get('faces', []), num_samples, backend, device)

    def show_studio_scene(self):
        """Display the current 3D studio scene."""
        if not self.config.enabled:
            return False
        if self.get_scene() is not None:
            self._push_scene()
            self.set_current_view("3d_studio")
            logger.info("[Visual Display] Studio scene displayed")
            return True
        return False

    def show_image(self, image_path: str, title: str = "Image"):
        """Display an image."""
        if not self.config.enabled:
            return False

        try:
            # Store image for display
            self._visual_data[f"image_{title}"] = {
                'type': 'image',
                'path': image_path,
                'title': title
            }
            logger.info(f"[Visual Display] Image queued: {title}")
            return True
        except Exception as e:
            logger.error(f"[Visual Display] Error showing image: {e}")
            return False

    def show_visual_output(self, action_name: str, output_data: Any):
        """Show visual output from an action."""
        try:
            # Dispatch based on action type
            if action_name.startswith('studio_') or action_name in ['create', 'transform', 'boolean']:
                return self._show_studio_output(output_data)
            elif action_name.startswith('globe_'):
                return self._show_globe_output(output_data)
            elif action_name.startswith('screen_'):
                return self._show_screen_output(output_data)
            else:
                logger.debug(f"[Visual Display] No visual display for action: {action_name}")
                return False
        except Exception as e:
            logger.error(f"[Visual Display] Error in show_visual_output: {e}")
            return False

    def _show_studio_output(self, output_data: Any):
        """Show studio-related visual output."""
        if isinstance(output_data, dict):
            # Mesh data
            if 'vertices' in output_data and 'faces' in output_data:
                name = output_data.get('name', 'unnamed')
                return self.show_3d_model(name, output_data)

        # Fall back to showing full scene
        return self.show_studio_scene()

    def _show_globe_output(self, output_data: Any):
        """Show God's Eye View visual output."""
        # Globe outputs are handled by apps/gods-eye-view
        logger.info("[Visual Display] Globe output - handled by GEV app")
        return True

    def _show_screen_output(self, output_data: Any):
        """Show screen capture visual output."""
        if isinstance(output_data, str):
            return self.show_image(output_data, "Screen Capture")
        return False

    def set_current_view(self, view_name: str):
        """Set the current visual display view."""
        self._current_view = view_name
        logger.debug(f"[Visual Display] Current view: {view_name}")

    def get_current_view(self) -> str:
        """Get current view name."""
        return self._current_view

    def get_widget(self, view_name: str = None) -> Optional[Any]:
        """Get widget for a view."""
        view_name = view_name or self._current_view
        return self._widgets.get(view_name)

    def clear_display(self):
        """Clear all visual displays and the shared studio scene."""
        for widget in self._widgets.values():
            if hasattr(widget, 'clear'):
                widget.clear()

        if self._studio_scene is not None:
            try:
                self._studio_scene.clear()
            except Exception:
                pass
        self._visual_data.clear()
        logger.info("[Visual Display] Display cleared")

    def get_display_status(self) -> Dict[str, Any]:
        """Get status of visual display system."""
        return {
            'enabled': self.config.enabled,
            'current_view': self._current_view,
            'widgets_available': list(self._widgets.keys()),
            'studio_scene_objects': len(self._studio_scene.objects) if self._studio_scene else 0,
            'visual_data_count': len(self._visual_data),
            'qt_available': QT_AVAILABLE
        }


# Global instance
_visual_manager: Optional[VisualDisplayManager] = None


def get_visual_display_manager() -> VisualDisplayManager:
    """Get the global visual display manager instance."""
    global _visual_manager
    if _visual_manager is None:
        _visual_manager = VisualDisplayManager()
        _visual_manager.initialize()
    return _visual_manager


def show_visual_output(action_name: str, output_data: Any) -> bool:
    """Convenience function to show visual output from an action."""
    manager = get_visual_display_manager()
    return manager.show_visual_output(action_name, output_data)


def show_3d_model(name: str, mesh_data: Optional[Dict] = None) -> bool:
    """Convenience function to show a 3D model."""
    manager = get_visual_display_manager()
    return manager.show_3d_model(name, mesh_data)


def show_studio_scene():
    """Convenience function to show current studio scene."""
    manager = get_visual_display_manager()
    return manager.show_studio_scene()


def show_image(image_path: str, title: str = "Image") -> bool:
    """Convenience function to show an image."""
    manager = get_visual_display_manager()
    return manager.show_image(image_path, title)
