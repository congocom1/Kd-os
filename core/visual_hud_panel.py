"""
core/visual_hud_panel.py — Visual Display HUD Panel

Adds a visual display panel to the JARVIS HUD for 3D models, images, and visual outputs.
Integrates with core.visual_display_manager and core.visual_display.

Usage:
    from core.visual_hud_panel import VisualHudPanel

    panel = VisualHudPanel()
    panel.show_model("cube")
    panel.show_image("/path/to/image.png")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger("jarvis.visual_hud")

try:
    from PyQt6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
    )
    from PyQt6.QtCore import Qt, pyqtSignal
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False
    QWidget = object  # Type stub
    pyqtSignal = None


class VisualHudPanel(QWidget):
    """Visual display panel for the JARVIS HUD."""

    # Signals
    model_changed = pyqtSignal(str) if QT_AVAILABLE else None
    display_cleared = pyqtSignal() if QT_AVAILABLE else None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_display_type = "none"
        self._current_content = None
        self._setup_ui()
        self._setup_visual_manager()

    def _setup_ui(self):
        """Setup the UI layout."""
        if not QT_AVAILABLE:
            return

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Header
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(5, 5, 5, 5)

        self._title_label = QLabel("Visual Display")
        self._title_label.setStyleSheet("""
            QLabel {
                color: #00e5ff;
                font-weight: bold;
                font-size: 12pt;
            }
        """)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self.clear_display)
        self._clear_btn.setMaximumWidth(60)

        header_layout.addWidget(self._title_label)
        header_layout.addStretch()
        header_layout.addWidget(self._clear_btn)

        # Content area
        self._content_widget = QWidget()
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(5, 5, 5, 5)

        # Placeholder for 3D display or image
        self._placeholder = QLabel("No visual content\n\nCreate 3D models or display images")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("""
            QLabel {
                color: #7a9aa6;
                font-size: 11pt;
                background-color: rgba(0, 10, 16, 200);
                border: 1px solid rgba(0, 80, 100, 100);
                border-radius: 4px;
                padding: 20px;
            }
        """)
        self._content_layout.addWidget(self._placeholder)

        layout.addWidget(header)
        layout.addWidget(self._content_widget)

        self.setLayout(layout)
        self.setMinimumHeight(300)
        self.setMaximumHeight(600)

    def _setup_visual_manager(self):
        """Setup visual display manager connection."""
        try:
            from core.visual_display_manager import get_visual_display_manager
            self._visual_manager = get_visual_display_manager()
            logger.info("[Visual HUD] Connected to visual display manager")
        except Exception as e:
            logger.warning(f"[Visual HUD] Could not connect to visual manager: {e}")
            self._visual_manager = None

    def show_model(self, model_name: str, mesh_data: Optional[Dict] = None):
        """Display a 3D model."""
        if not QT_AVAILABLE:
            return

        try:
            from core.visual_display_manager import show_3d_model
            success = show_3d_model(model_name, mesh_data)

            if success:
                self._current_display_type = "3d_model"
                self._current_content = model_name
                self._title_label.setText(f"3D Studio: {model_name}")
                self._update_placeholder(f"3D Model: {model_name}\nRendering in 3D viewer")
                self.model_changed.emit(model_name)
                logger.info(f"[Visual HUD] Showing model: {model_name}")
            else:
                logger.warning(f"[Visual HUD] Could not show model: {model_name}")

        except Exception as e:
            logger.error(f"[Visual HUD] Error showing model: {e}")

    def show_scene(self):
        """Display the entire 3D scene."""
        if not QT_AVAILABLE:
            return

        try:
            from core.visual_display_manager import show_studio_scene
            success = show_studio_scene()

            if success:
                self._current_display_type = "3d_scene"
                self._current_content = "scene"
                self._title_label.setText("3D Studio: Scene")
                self._update_placeholder("3D Scene\nAll objects displayed")
                logger.info("[Visual HUD] Showing scene")

        except Exception as e:
            logger.error(f"[Visual HUD] Error showing scene: {e}")

    def show_image(self, image_path: str):
        """Display an image."""
        if not QT_AVAILABLE:
            return

        try:
            path = Path(image_path)
            if not path.exists():
                self._update_placeholder(f"Image not found:\n{image_path}")
                return

            # For now, show placeholder with path
            # Full image loading would require QPixmap with proper scaling
            self._current_display_type = "image"
            self._current_content = str(path)
            self._title_label.setText(f"Image: {path.name}")
            self._update_placeholder(f"Image Display\n{path.name}\n{path.parent}")
            logger.info(f"[Visual HUD] Showing image: {path.name}")

        except Exception as e:
            logger.error(f"[Visual HUD] Error showing image: {e}")

    def show_text(self, text: str, title: str = "Visual Output"):
        """Display text in visual panel."""
        if not QT_AVAILABLE:
            return

        self._current_display_type = "text"
        self._current_content = text
        self._title_label.setText(f"Visual: {title}")
        self._update_placeholder(f"{title}\n\n{text[:500]}")
        logger.info(f"[Visual HUD] Showing text: {title}")

    def clear_display(self):
        """Clear the visual display."""
        if not QT_AVAILABLE:
            return

        self._current_display_type = "none"
        self._current_content = None
        self._title_label.setText("Visual Display")
        self._update_placeholder("No visual content\n\nCreate 3D models or display images")

        # Clear visual manager
        if self._visual_manager:
            self._visual_manager.clear_display()

        if self.display_cleared:
            self.display_cleared.emit()

        logger.info("[Visual HUD] Display cleared")

    def _update_placeholder(self, text: str):
        """Update the placeholder text."""
        if hasattr(self, '_placeholder'):
            self._placeholder.setText(text)

    def get_display_status(self) -> Dict[str, Any]:
        """Get current display status."""
        return {
            'type': self._current_display_type,
            'content': self._current_content,
            'qt_available': QT_AVAILABLE,
            'title': self._title_label.text() if hasattr(self, '_title_label') else "None"
        }

    def set_task_mode(self, mode: str):
        """Update visual display based on task mode."""
        if mode == "studio":
            self._title_label.setStyleSheet("""
                QLabel {
                    color: #00ff9d;
                    font-weight: bold;
                    font-size: 12pt;
                }
            """)
        elif mode == "cinema":
            self._title_label.setStyleSheet("""
                QLabel {
                    color: #ffaa00;
                    font-weight: bold;
                    font-size: 12pt;
                }
            """)
        else:
            self._title_label.setStyleSheet("""
                QLabel {
                    color: #00e5ff;
                    font-weight: bold;
                    font-size: 12pt;
                }
            """)


# Factory function for easy integration
def create_visual_hud_panel(parent=None) -> Optional[VisualHudPanel]:
    """Create a visual HUD panel."""
    if not QT_AVAILABLE:
        logger.warning("[Visual HUD] Qt not available, cannot create panel")
        return None

    return VisualHudPanel(parent)


# Integration helper for studio modeler
def integrate_visual_display_with_studio():
    """Integrate visual display with studio modeler automatically."""
    try:
        from core.visual_display_manager import get_visual_display_manager

        manager = get_visual_display_manager()
        manager.initialize()

        logger.info("[Visual HUD] Studio integration complete")
        return True

    except Exception as e:
        logger.error(f"[Visual HUD] Integration failed: {e}")
        return False
