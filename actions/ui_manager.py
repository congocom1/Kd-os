"""
actions/ui_manager.py — Smart UI: manage HUD widgets, themes, and views.

Upgrade from a chat interface to a full operating system desktop.

Features:
  - System bar with real-time resource gauges
  - Notification center with floating alerts
  - Settings panel with OS-level controls
  - Dashboard widget grid
  - Theme support (light/dark/auto)
"""

import json
import logging
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFrame, QProgressBar, QScrollArea, QGraphicsDropShadowEffect,
    QFileDialog, QGraphicsOpacityEffect,
)

logger = logging.getLogger("ui_manager")

from ui import JarvisUI, C


class SystemBar(QWidget):
    """Top system bar showing real-time resource gauges."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cpu = 0.0
        self._ram = 0.0
        self._disk = 0.0
        self._processes = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        self._cpu_label = QLabel("CPU: --%")
        self._cpu_bar = QProgressBar()
        self._cpu_bar.setRange(0, 100)
        self._cpu_bar.setValue(0)

        self._ram_label = QLabel("RAM: --%")
        self._ram_bar = QProgressBar()
        self._ram_bar.setRange(0, 100)
        self._ram_bar.setValue(0)

        self._disk_label = QLabel("Disk: --%")
        self._disk_bar = QProgressBar()
        self._disk_bar.setRange(0, 100)
        self._disk_bar.setValue(0)

        self._proc_label = QLabel("Proc: --")
        self._proc_bar = QProgressBar()
        self._proc_bar.setRange(0, 200)
        self._proc_bar.setValue(0)

        layout.addWidget(self._cpu_label)
        layout.addWidget(self._cpu_bar)
        layout.addWidget(self._ram_label)
        layout.addWidget(self._ram_bar)
        layout.addWidget(self._disk_label)
        layout.addWidget(self._disk_bar)
        layout.addWidget(self._proc_label)
        layout.addWidget(self._proc_bar)

        # Update timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update_gauges)
        self._timer.start(1000)

    def set_system(self, data: dict):
        """Update gauges from system status."""
        self._cpu = data.get("cpu_percent", 0)
        self._ram = data.get("memory_percent", 0)
        self._disk = data.get("disk_percent", 0)
        self._processes = data.get("process_count", 0)

        self._cpu_label.setText(f"CPU: {self._cpu:.0f}%")
        self._cpu_bar.setValue(self._cpu)
        self._ram_label.setText(f"RAM: {self._ram:.0f}%")
        self._ram_bar.setValue(self._ram)
        self._disk_label.setText(f"Disk: {self._disk:.0f}%")
        self._disk_bar.setValue(self._disk)
        self._proc_label.setText(f"Proc: {self._processes}")

    def update_gauges(self):
        self.update()


class NotificationCenter(QFrame):
    """Floating notification panel with priority routing."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._notifications = []
        self._max_visible = 5

        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Sunken)
        self.setFixedWidth(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self._header = QLabel("Notifications")
        self._header.setStyleSheet(f"color: {C.PRI}; font-weight: bold;")
        layout.addWidget(self._header)

        self._list = QLabel("")
        self._list.setWordWrap(True)
        self._list.setStyleSheet(f"background: {C.PANEL}; "
                                  f"border: 1px solid {C.BORDER}; "
                                  f"padding: 8px;")
        layout.addWidget(self._list)

        self._clear_btn = QPushButton("Clear All")
        self._clear_btn.clicked.connect(self.clear)
        self._clear_btn.setStyleSheet(f"background: {C.PANEL2}; "
                                       f"color: {C.TEXT}; "
                                       f"border: 1px solid {C.BORDER};")
        layout.addWidget(self._clear_btn)

    def add(self, title, message, priority="info"):
        markers = {"info": "ℹ", "warning": "⚠", "critical": "🛑"}
        self._notifications.append((title, message, priority))
        if len(self._notifications) > self._max_visible:
            self._notifications.pop(0)

        self._render()

    def clear(self):
        self._notifications.clear()
        self._list.setText("")
        self._render()

    def _render(self):
        if not self._notifications:
            self._list.setText("No notifications")
            return
        lines = []
        for title, msg, pri in self._notifications:
            markers = {"info": "ℹ", "warning": "⚠", "critical": "🛑"}
            lines.append(f"{markers.get(pri, '⚠')} {title}: {msg}")
        self._list.setText("\n".join(lines))


class SettingsPanel(QFrame):
    """System settings panel with OS-level controls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Sunken)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._header = QLabel("Settings")
        self._header.setStyleSheet(f"color: {C.PRI}; font-weight: bold;")
        layout.addWidget(self._header)

        self._theme_label = QLabel("Theme: Dark")
        self._theme_label.setStyleSheet(f"color: {C.TEXT_DIM};")
        layout.addWidget(self._theme_label)

        self._theme_btn = QPushButton("Toggle Theme")
        self._theme_btn.setStyleSheet(f"background: {C.PANEL2}; "
                                       f"color: {C.TEXT}; "
                                       f"border: 1px solid {C.BORDER};")
        self._theme_btn.clicked.connect(self._toggle_theme)
        layout.addWidget(self._theme_btn)

        self._vol_label = QLabel("Volume: --%")
        self._vol_label.setStyleSheet(f"color: {C.TEXT_DIM};")
        layout.addWidget(self._vol_label)

        self._vol_btn = QPushButton("Adjust Volume")
        self._vol_btn.setStyleSheet(f"background: {C.PANEL2}; "
                                     f"color: {C.TEXT}; "
                                     f"border: 1px solid {C.BORDER};")
        layout.addWidget(self._vol_btn)

        self._screen_btn = QPushButton("Toggle Screen Capture")
        self._screen_btn.setStyleSheet(f"background: {C.PANEL2}; "
                                        f"color: {C.TEXT}; "
                                        f"border: 1px solid {C.BORDER};")
        layout.addWidget(self._screen_btn)

        self._help_btn = QPushButton("System Help")
        self._help_btn.setStyleSheet(f"background: {C.PANEL2}; "
                                      f"color: {C.TEXT}; "
                                      f"border: 1px solid {C.BORDER};")
        layout.addWidget(self._help_btn)

    def _toggle_theme(self):
        # Theme switching logic here
        pass


class DockPanel(QFrame):
    """Bottom dock with quick-launch buttons for OS tools."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Sunken)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)

        items = [
            ("⚠ Alerts", "❌ Shutdown"),
            ("📊 System", "🔍 Find"),
            ("🔌 Network", "🏗 Build"),
            ("📦 Backup", "🧹 Clean"),
        ]

        for label, tool in items:
            btn = QPushButton(label)
            btn.setFixedHeight(28)
            btn.setStyleSheet(f"background: {C.PANEL2}; "
                              f"color: {C.TEXT}; "
                              f"border: 1px solid {C.BORDER}; "
                              f"border-radius: 4px;")
            layout.addWidget(btn)


class UIManager:
    """Manages all UI widgets for the OS."""

    def __init__(self, ui: JarvisUI):
        self.ui = ui
        self.system_bar = SystemBar(ui)
        self.notif_center = NotificationCenter(ui)
        self.dock = DockPanel(ui)

    def install(self, parent_layout: QVBoxLayout):
        """Install the OS UI into the main window layout."""
        # Create a central container for the OS layer
        container = QWidget()
        main_layout = QVBoxLayout(container)

        # System bar at top
        main_layout.addWidget(self.system_bar)

        # Left: notification center
        left_panel = QFrame()
        left_panel.setStyleSheet(f"background: {C.PANEL};")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.notif_center)

        # Right: friends area placeholder
        right_panel = QFrame()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("Friends Panel"))
        right_layout.addWidget(QLabel("Add friends to chat with them"))

        # Bottom dock
        main_layout.addWidget(self.dock)

        parent_layout.addWidget(container)
