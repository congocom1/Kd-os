"""core/boot_splash.py — Cinematic boot splash for JARVIS.

Displays a frameless splash screen with a progress indicator and status lines
while the unified app initializes. Can be extended to wait for GEV/Kronos
services to report healthy before fading into the main HUD.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QRectF
from PyQt6.QtGui import (
    QFont, QPainter, QColor, QPen, QRadialGradient,
)
from PyQt6.QtWidgets import QApplication, QProgressBar, QLabel, QVBoxLayout, QWidget

from core import cinematic_theme


class BootSplash(QWidget):
    """Frameless cinematic boot splash."""

    finished = pyqtSignal()

    def __init__(self, app_name: str = "JARVIS", parent=None):
        super().__init__(parent)
        self._app_name = app_name.upper()
        self._palette = cinematic_theme.load_palette()
        self._messages = [
            "Initializing neural core...",
            "Loading cinematic interface...",
            "Mounting God's Eye View...",
            "Arming Kronos forecast engine...",
            "Synchronizing memory banks...",
            "Establishing secure uplink...",
        ]
        self._index = 0

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SplashScreen
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(540, 400)

        # Center on primary screen
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2,
        )

        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def _build_ui(self):
        self.setStyleSheet(f"""
            QWidget {{
                background: rgba(0, 5, 8, 245);
                color: {self._palette['text']};
                font-family: "Rajdhani", "Orbitron", "Segoe UI", sans-serif;
            }}
            QLabel {{
                background: transparent;
                color: {self._palette['accent']};
            }}
            QProgressBar {{
                background: rgba(0, 20, 30, 200);
                border: 1px solid {self._palette['border']};
                border-radius: 3px;
                text-align: center;
                color: {self._palette['text']};
            }}
            QProgressBar::chunk {{
                background: {self._palette['accent']};
                border-radius: 2px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(16)

        # App name / title
        title = QLabel(self._app_name)
        title_font = QFont("Orbitron", 32, QFont.Weight.Bold)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {self._palette['accent']};")
        layout.addWidget(title)

        # Subtitle
        subtitle = QLabel("UNIFIED COMMAND CENTER")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"color: {self._palette['text_dim']};")
        layout.addWidget(subtitle)

        layout.addSpacing(96)   # the painted arc reactor lives here

        layout.addStretch()

        # Status line
        self._status = QLabel(self._messages[0])
        self._status.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._status.setStyleSheet(f"color: {self._palette['text']};")
        layout.addWidget(self._status)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, len(self._messages))
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(8)
        layout.addWidget(self._progress)

    def _tick(self):
        self._index += 1
        if self._index >= len(self._messages):
            self._timer.stop()
            self.finished.emit()
            self.close()
            return
        self._status.setText(self._messages[self._index])
        self._progress.setValue(self._index)
        self.update()   # reactor power-up frame

    def _paint_reactor_boot(self, painter: QPainter) -> None:
        """Arc-reactor power-up: coils and core light up with the progress bar."""
        cx, cy, r = self.width() / 2, 158.0, 42.0
        power = self._index / max(1, len(self._messages) - 1)

        accent = QColor(self._palette["accent"])
        core = QColor(self._palette.get("reactor_core", "#bfe9ff"))

        # Core glow grows with power
        glow = QRadialGradient(cx, cy, r * 1.6)
        glow.setColorAt(0.0, QColor(core.red(), core.green(), core.blue(),
                                    int(200 * power)))
        glow.setColorAt(0.6, QColor(core.red(), core.green(), core.blue(),
                                    int(60 * power)))
        glow.setColorAt(1.0, QColor(core.red(), core.green(), core.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(cx - r * 1.6, cy - r * 1.6, r * 3.2, r * 3.2))

        # Housing ring
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(),
                                   90 + int(120 * power)), 2.4))
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # 10 coil segments light up one by one
        coil = QRectF(cx - r * 1.22, cy - r * 1.22, r * 2.44, r * 2.44)
        lit = int(power * 10)
        for i in range(10):
            on = i < lit
            alpha = 220 if on else 45
            pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), alpha),
                       4.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            painter.drawArc(coil, (i * 36 + 4) * 16, 28 * 16)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background with subtle border glow
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 5, 8, 245))
        painter.drawRoundedRect(self.rect(), 12, 12)

        accent = QColor(self._palette["accent"])
        pen = QPen(accent)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)

        self._paint_reactor_boot(painter)

        painter.end()

    def start(self, interval_ms: int = 450):
        """Show the splash and advance status messages on a timer."""
        self.show()
        self.raise_()
        self.activateWindow()
        self._timer.start(interval_ms)


def show_boot_splash(app_name: str = "JARVIS", interval_ms: int = 450):
    """Convenience: create, show, and return the splash widget."""
    splash = BootSplash(app_name)
    splash.start(interval_ms)
    return splash
