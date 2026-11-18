"""
core/visual_display_frontend.py — Cinematic Visual Display Frontend

Production-grade PyQt6 frontend for JARVIS 3D Studio with distinctive
retro-futuristic brutalist design.

Aesthetic Direction: Cinematic Tron Futurism
- Holographic workshop metaphor
- Asymmetrical brutalist layout
- Living grid with breathing animations
- Glassmorphism panels with cyan accents
"""

from __future__ import annotations

import logging

logger = logging.getLogger("jarvis.visual.frontend")

try:
    from PyQt6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QFrame, QTreeWidget, QTreeWidgetItem, QDoubleSpinBox,
        QFormLayout, QTabWidget
    )
    from PyQt6.QtCore import Qt, pyqtSignal, QTimer
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False
    QWidget = object
    pyqtSignal = None


class CinematicVisualWorkshop(QWidget):
    """Cinematic visual display frontend with Tron futurism design."""

    model_selected = pyqtSignal(str) if QT_AVAILABLE else None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_model = None
        self._theme = "tron"

        if QT_AVAILABLE:
            self._setup_ui()
            self._setup_styling()
            self._start_animations()

    def _setup_ui(self):
        """Setup the cinematic UI layout."""
        # Outer layout: accent bar on top, then three columns below
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # Accent bar at top (full width)
        self._accent_bar = self._create_accent_bar()
        outer_layout.addWidget(self._accent_bar)

        # Three-column workshop row
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left panel - Model Tree (brutalist file explorer) — fixed width
        self._left_panel = self._create_model_tree_panel()
        self._left_panel.setFixedWidth(180)
        main_layout.addWidget(self._left_panel)

        # Center - 3D Viewport with diagonal cut — stretches
        self._viewport_container = self._create_viewport_container()
        main_layout.addWidget(self._viewport_container, stretch=1)

        # Right panel - Properties (glassmorphism) — fixed width
        self._right_panel = self._create_properties_panel()
        self._right_panel.setFixedWidth(320)
        main_layout.addWidget(self._right_panel)

        outer_layout.addLayout(main_layout, stretch=1)

        self.setMinimumSize(800, 500)

    def _create_model_tree_panel(self) -> QWidget:
        """Create the brutalist model tree panel."""
        panel = QFrame()
        panel.setObjectName("modelTreePanel")
        panel.setStyleSheet("""
            QFrame#modelTreePanel {
                background: rgba(0, 10, 16, 235);
                border-right: 1px solid #003340;
            }
        """)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)

        # Header
        header = QLabel("MODEL TREE")
        header.setStyleSheet("""
            QLabel {
                color: #00e5ff;
                font-family: 'JetBrains Mono', monospace;
                font-size: 11pt;
                font-weight: 700;
                letter-spacing: 1px;
                padding: 8px 0;
                border-bottom: 1px solid #003340;
                margin-bottom: 8px;
            }
        """)
        layout.addWidget(header)

        # Tree widget
        self._model_tree = QTreeWidget()
        self._model_tree.setHeaderHidden(True)
        self._model_tree.setStyleSheet("""
            QTreeWidget {
                background: transparent;
                border: none;
                color: #e0f7ff;
                font-family: 'JetBrains Mono', monospace;
                font-size: 10pt;
            }
            QTreeWidget::item {
                padding: 6px 4px;
                border-left: 2px solid transparent;
            }
            QTreeWidget::item:hover {
                background: rgba(0, 136, 170, 0.2);
                border-left: 2px solid #00e5ff;
            }
            QTreeWidget::item:selected {
                background: rgba(0, 136, 170, 0.4);
                border-left: 2px solid #00e5ff;
                color: white;
            }
        """)
        self._model_tree.itemClicked.connect(self._on_model_selected)
        layout.addWidget(self._model_tree)

        # Transform shortcuts
        transform_box = self._create_transform_shortcuts()
        layout.addWidget(transform_box)

        return panel

    def _create_transform_shortcuts(self) -> QFrame:
        """Create transform shortcut buttons."""
        box = QFrame()
        box.setStyleSheet("""
            QFrame {
                background: rgba(0, 20, 30, 0.8);
                border: 1px solid #003340;
                border-radius: 4px;
                padding: 8px;
                margin-top: 12px;
            }
        """)

        layout = QFormLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Scale inputs
        self._scale_x = QDoubleSpinBox()
        self._setup_spinbox(self._scale_x)
        layout.addRow("Scale X:", self._scale_x)

        self._scale_y = QDoubleSpinBox()
        self._setup_spinbox(self._scale_y)
        layout.addRow("Scale Y:", self._scale_y)

        self._scale_z = QDoubleSpinBox()
        self._setup_spinbox(self._scale_z)
        layout.addRow("Scale Z:", self._scale_z)

        return box

    def _setup_spinbox(self, spinbox: QDoubleSpinBox):
        """Setup cinematic styling for spinbox."""
        spinbox.setRange(-1000, 1000)
        spinbox.setSingleStep(0.1)
        spinbox.setDecimals(2)
        spinbox.setStyleSheet("""
            QDoubleSpinBox {
                background: rgba(0, 20, 30, 0.9);
                border: 1px solid #003340;
                color: #e0f7ff;
                font-family: 'JetBrains Mono', monospace;
                font-size: 10pt;
                padding: 4px 8px;
                border-radius: 2px;
            }
            QDoubleSpinBox:focus {
                border: 1px solid #00e5ff;
                background: rgba(0, 20, 30, 1.0);
            }
        """)

    def _create_viewport_container(self) -> QWidget:
        """Create the 3D viewport container with diagonal cut."""
        container = QWidget()
        container.setObjectName("viewportContainer")
        container.setStyleSheet("""
            QWidget#viewportContainer {
                background: qradialgradient(
                    cx: 0.5, cy: 0.5,
                    fx: 0.5, fy: 0.5,
                    radius: 0.8,
                    stop: 0 rgba(0, 30, 60, 0.8),
                    stop: 1 rgba(0, 7, 10, 1.0)
                );
                border-left: 1px solid #003340;
                border-right: 1px solid #003340;
            }
        """)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        # Viewport placeholder (actual OpenGL widget would go here)
        viewport = QFrame()
        viewport.setObjectName("viewport")
        viewport.setStyleSheet("""
            QFrame#viewport {
                background: rgba(0, 10, 16, 200);
                border: 1px solid #00e5ff;
                border-radius: 8px;
            }
        """)

        # Add holographic grid overlay
        grid_label = QLabel(
            "HOLOGRAPHIC WORKSPACE\n[3D VIEWPORT]\n\nModels render here with\ncinematic lighting and\ncyan accent glow"
        )
        grid_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid_label.setStyleSheet("""
            QLabel {
                color: #7a9aa6;
                font-family: 'JetBrains Mono', monospace;
                font-size: 12pt;
                background: transparent;
            }
        """)

        viewport_layout = QVBoxLayout(viewport)
        viewport_layout.addWidget(grid_label)
        layout.addWidget(viewport)

        return container

    def _create_properties_panel(self) -> QWidget:
        """Create the properties panel with glassmorphism."""
        panel = QFrame()
        panel.setObjectName("propertiesPanel")
        panel.setStyleSheet("""
            QFrame#propertiesPanel {
                background: rgba(0, 10, 16, 235);
                border-left: 1px solid #003340;
            }
        """)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header
        header = QLabel("PROPERTIES")
        header.setStyleSheet("""
            QLabel {
                color: #00e5ff;
                font-family: 'JetBrains Mono', monospace;
                font-size: 11pt;
                font-weight: 700;
                letter-spacing: 1px;
                padding: 8px 0;
                border-bottom: 1px solid #003340;
                margin-bottom: 12px;
            }
        """)
        layout.addWidget(header)

        # Tabs
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #003340;
                background: rgba(0, 20, 30, 0.8);
            }
            QTabBar::tab {
                background: rgba(0, 20, 30, 0.8);
                color: #7a9aa6;
                padding: 8px 16px;
                border: 1px solid #003340;
                border-bottom: none;
            }
            QTabBar::tab:selected {
                background: rgba(0, 136, 170, 0.4);
                color: #e0f7ff;
                border-color: #00e5ff;
            }
        """)

        # Transform tab
        transform_tab = self._create_transform_tab()
        tabs.addTab(transform_tab, "TRANSFORM")

        # Material tab
        material_tab = self._create_material_tab()
        tabs.addTab(material_tab, "MATERIAL")

        # Metadata tab
        metadata_tab = self._create_metadata_tab()
        tabs.addTab(metadata_tab, "METADATA")

        layout.addWidget(tabs)

        # History
        history = self._create_history_panel()
        layout.addWidget(history)

        return panel

    def _create_transform_tab(self) -> QWidget:
        """Create transform properties tab."""
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(8)

        # Position
        for axis in ['X', 'Y', 'Z']:
            spin = QDoubleSpinBox()
            self._setup_spinbox(spin)
            layout.addRow(f"Position {axis}:", spin)
            setattr(self, f'_pos_{axis.lower()}', spin)

        # Rotation
        for axis in ['X', 'Y', 'Z']:
            spin = QDoubleSpinBox()
            self._setup_spinbox(spin)
            layout.addRow(f"Rotation {axis}:", spin)
            setattr(self, f'_rot_{axis.lower()}', spin)

        return widget

    def _create_material_tab(self) -> QWidget:
        """Create material properties tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        info = QLabel(
            "Material properties\n(Emissive, Roughness,\nMetallic factors)"
        )
        info.setStyleSheet("""
            QLabel {
                color: #7a9aa6;
                font-family: 'JetBrains Mono', monospace;
                font-size: 10pt;
                padding: 20px;
            }
        """)
        layout.addWidget(info)

        return widget

    def _create_metadata_tab(self) -> QWidget:
        """Create metadata tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self._metadata_label = QLabel("Verts: --\nFaces: --\nBounds: --")
        self._metadata_label.setStyleSheet("""
            QLabel {
                color: #e0f7ff;
                font-family: 'JetBrains Mono', monospace;
                font-size: 10pt;
                background: rgba(0, 20, 30, 0.8);
                border: 1px solid #003340;
                padding: 12px;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self._metadata_label)

        return widget

    def _create_history_panel(self) -> QFrame:
        """Create operation history panel."""
        frame = QFrame()
        frame.setObjectName("historyPanel")
        frame.setStyleSheet("""
            QFrame#historyPanel {
                background: rgba(0, 20, 30, 0.6);
                border: 1px solid #003340;
                border-radius: 4px;
                margin-top: 12px;
            }
        """)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)

        title = QLabel("HISTORY")
        title.setStyleSheet("""
            QLabel {
                color: #7a9aa6;
                font-family: 'JetBrains Mono', monospace;
                font-size: 9pt;
                font-weight: 700;
            }
        """)
        layout.addWidget(title)

        self._history_label = QLabel(
            "No operations yet\n\nModels appear here as\ncraftsman marks"
        )
        self._history_label.setStyleSheet("""
            QLabel {
                color: #7a9aa6;
                font-family: 'JetBrains Mono', monospace;
                font-size: 9pt;
                padding: 8px 0;
            }
        """)
        layout.addWidget(self._history_label)

        return frame

    def _create_accent_bar(self) -> QFrame:
        """Create top accent bar."""
        bar = QFrame()
        bar.setMaximumHeight(40)
        bar.setStyleSheet("""
            QFrame {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00070a, stop:0.5 #001a2e, stop:1 #00070a
                );
                border-bottom: 2px solid #00e5ff;
            }
        """)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 8, 16, 8)

        title = QLabel("JARVIS 3D WORKSHOP")
        title.setStyleSheet("""
            QLabel {
                color: #00e5ff;
                font-family: 'JetBrains Mono', monospace;
                font-size: 12pt;
                font-weight: 700;
                letter-spacing: 1px;
            }
        """)
        layout.addWidget(title)

        layout.addStretch()

        scene_label = QLabel("SCENE: workshop_beta")
        scene_label.setStyleSheet("""
            QLabel {
                color: #7a9aa6;
                font-family: 'JetBrains Mono', monospace;
                font-size: 9pt;
            }
        """)
        layout.addWidget(scene_label)

        return bar

    def _setup_styling(self):
        """Setup application-wide styling."""
        if not hasattr(self, 'setStyleSheet'):
            return

        self.setStyleSheet("""
            QWidget {
                background: #00070a;
                color: #e0f7ff;
                font-family: 'Inter', system-ui, sans-serif;
            }
        """)

    def _start_animations(self):
        """Start ambient animations."""
        # Grid pulse animation would go here
        # Using QTimer for breathing effect
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._on_pulse_tick)
        self._pulse_timer.start(3000)  # 3 second loop

    def _on_pulse_tick(self):
        """Handle pulse animation tick."""
        # Grid opacity animation
        pass

    def _on_model_selected(self, item, column):
        """Handle model selection."""
        name = item.text(0)
        self._current_model = name

        if self.model_selected:
            self.model_selected.emit(name)

        # Update metadata display
        self._update_metadata_display(name)

        # Pulse animation
        self._pulse_model_selection(item)

    def _update_metadata_display(self, model_name: str):
        """Update metadata panel with model info."""
        if hasattr(self, '_metadata_label'):
            # This would fetch real data from studio engine
            self._metadata_label.setText(
                f"Model: {model_name}\nVerts: 1,024\nFaces: 512\nBounds: ±2.0"
            )

    def _pulse_model_selection(self, item):
        """Animate model selection."""
        # Visual pulse effect
        pass

    def load_scene(self, scene):
        """Load a studio scene into the frontend."""
        if not QT_AVAILABLE or not hasattr(self, '_model_tree'):
            return

        self._model_tree.clear()

        try:
            from core.studio_engine import Scene
            if isinstance(scene, Scene):
                for name in scene.list_names():
                    item = QTreeWidgetItem([name])
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsSelectable)

                    # Color code by type
                    if 'cube' in name.lower() or 'box' in name.lower():
                        # Primitive cyan
                        pass
                    # Add more items...

                    self._model_tree.addTopLevelItem(item)

                logger.info(
                    "[Visual Frontend] Loaded scene with %d models",
                    len(scene.list_names()),
                )
        except Exception as e:
            logger.error(f"[Visual Frontend] Error loading scene: {e}")

    def set_theme(self, theme_name: str):
        """Change visual theme and reapply palette."""
        self._theme = theme_name
        try:
            from core.cinematic_theme import PALETTES
            palette = PALETTES.get(theme_name, PALETTES.get("tron", {}))
        except Exception:
            palette = {}

        # Reapply accent bar gradient
        if hasattr(self, "_accent_bar") and palette:
            accent = palette.get("PRI", "#00e5ff")
            self._accent_bar.setStyleSheet(
                f"""
                QFrame {{
                    background: qlineargradient(
                        x1:0, y1:0, x2:1, y2:0,
                        stop:0 #00070a, stop:0.5 {accent}33, stop:1 #00070a
                    );
                    border-bottom: 2px solid {accent};
                }}
                """
            )

        logger.info(f"[Visual Frontend] Theme changed to {theme_name}")


def create_cinematic_workshop(parent=None):
    """Factory function to create the cinematic workshop frontend."""
    if not QT_AVAILABLE:
        logger.warning("[Visual Frontend] Qt not available")
        return None

    return CinematicVisualWorkshop(parent)
