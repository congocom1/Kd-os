"""
core/interactive_hud.py — Interactive HUD Enhancements (KD Upgrade).

Extends the existing HUD with:
  • Real-time telemetry widgets (CPU, GPU, memory, network)
  • Task progress visualization
  • Speaker identification display
  • Window context awareness
  • Interactive overlays (click-through, draggable)
  • Plugin/widget system for custom panels
  • Zero-regression: gated by INTERACTIVE_HUD flag

Integrates with: awareness_engine, window_manager, multi_person_voice, task_orchestration
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from core.feature_flags import is_enabled
from core.awareness_engine import get_awareness_engine, EventType

logger = logging.getLogger("jarvis.interactive_hud")


# ── HUD Widget Types ──────────────────────────────────────────────────────────

class WidgetType(Enum):
    METRICS = "metrics"           # System metrics (CPU, RAM, GPU, Net)
    TASK_PROGRESS = "task_progress"  # Current task progress bar
    SPEAKER_ID = "speaker_id"     # Active speaker identification
    WINDOW_CONTEXT = "window_context"  # Focused window info
    VOICE_VISUALIZER = "voice_visualizer"  # Audio waveform/spectrum
    CUSTOM = "custom"             # Plugin-defined widget


@dataclass
class WidgetConfig:
    """Configuration for a HUD widget."""
    widget_id: str
    widget_type: WidgetType
    title: str
    enabled: bool = True
    position: str = "top-right"  # top-left, top-right, bottom-left, bottom-right, center
    size: tuple[int, int] = (300, 200)  # width, height
    refresh_interval: float = 1.0  # seconds
    opacity: float = 0.9
    click_through: bool = False
    draggable: bool = True
    custom_data: dict = field(default_factory=dict)


@dataclass
class WidgetState:
    """Runtime state of a widget."""
    config: WidgetConfig
    data: dict = field(default_factory=dict)
    visible: bool = True
    last_update: float = 0.0
    error: str | None = None


# ── Data Providers ────────────────────────────────────────────────────────────

class MetricsProvider:
    """Provides system metrics for HUD display."""

    def __init__(self):
        self._history: dict[str, list[tuple[float, float]]] = {
            "cpu": [], "memory": [], "gpu": [], "network_up": [], "network_down": []
        }
        self._max_history = 120  # 2 minutes at 1s intervals

    def collect(self) -> dict:
        """Collect current metrics."""
        import psutil
        now = time.time()

        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory().percent

        net = psutil.net_io_counters()
        net_up = net.bytes_sent / 1e6  # MB
        net_down = net.bytes_recv / 1e6

        gpu = self._get_gpu_usage()

        # Update history
        self._history["cpu"].append((now, cpu))
        self._history["memory"].append((now, mem))
        self._history["gpu"].append((now, gpu))
        self._history["network_up"].append((now, net_up))
        self._history["network_down"].append((now, net_down))

        # Trim history
        for key in self._history:
            if len(self._history[key]) > self._max_history:
                self._history[key] = self._history[key][-self._max_history:]

        return {
            "cpu": cpu,
            "memory": mem,
            "gpu": gpu,
            "network_up_mb": net_up,
            "network_down_mb": net_down,
            "history": {k: [v for _, v in vals] for k, vals in self._history.items()},
            "timestamp": now,
        }

    def _get_gpu_usage(self) -> float | None:
        """Get GPU usage if available."""
        try:
            import pynvml
            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            return float(util.gpu)
        except Exception:
            return None


class TaskProgressProvider:
    """Provides task progress data from orchestrator."""

    def __init__(self):
        self._current_task: dict | None = None

    def update_from_orchestrator(self, orchestrator) -> None:
        """Update from task orchestrator."""
        if not orchestrator:
            return
        tasks = orchestrator.list_tasks(status=None, limit=1)
        if tasks:
            task = tasks[0]
            if task.status.value in ("running", "pending"):
                self._current_task = {
                    "id": task.id,
                    "name": task.name,
                    "progress": task.progress,
                    "status": task.status.value,
                    "steps_total": len(task.steps),
                    "steps_completed": sum(1 for s in task.steps if s.status.value == "completed"),
                    "current_step": next((s.name for s in task.steps if s.status.value == "running"), None),
                }
            else:
                self._current_task = None
        else:
            self._current_task = None

    def get_data(self) -> dict:
        return self._current_task or {}


class SpeakerProvider:
    """Provides speaker identification data."""

    def __init__(self):
        self._current_speaker: str | None = None
        self._speaker_name: str | None = None
        self._confidence: float = 0.0

    def update_from_awareness(self, awareness) -> None:
        """Update from awareness engine."""
        if not awareness:
            return
        speaker_id = awareness.get_current_speaker()
        if speaker_id:
            self._current_speaker = speaker_id
            profile = awareness.get_speaker_profile(speaker_id)
            if profile:
                self._speaker_name = profile.get("name")
                self._confidence = 0.9
            else:
                self._speaker_name = f"Speaker {speaker_id[-4:]}"
                self._confidence = 0.5
        else:
            self._current_speaker = None
            self._speaker_name = None
            self._confidence = 0.0

    def get_data(self) -> dict:
        return {
            "speaker_id": self._current_speaker,
            "speaker_name": self._speaker_name,
            "confidence": self._confidence,
            "is_speaking": self._current_speaker is not None,
        }


class WindowContextProvider:
    """Provides focused window context."""

    def __init__(self):
        self._window_info: dict | None = None

    def update_from_window_manager(self, window_manager) -> None:
        """Update from window manager."""
        if not window_manager:
            return
        active = window_manager.get_active_window()
        if active:
            self._window_info = {
                "window_id": active.window_id,
                "title": active.title,
                "app_name": active.app_name,
                "bounds": active.bounds,
                "state": active.state.value,
                "pid": active.pid,
            }
        else:
            self._window_info = None

    def get_data(self) -> dict:
        return self._window_info or {}


class VoiceVisualizerProvider:
    """Provides audio visualization data."""

    def __init__(self):
        self._waveform: list[float] = []
        self._spectrum: list[float] = []
        self._is_speaking = False
        self._is_listening = False

    def update_audio(self, samples: list[float], is_speaking: bool = False, is_listening: bool = False) -> None:
        """Update with new audio samples."""
        self._waveform = samples[-200:]  # Keep last 200 samples
        self._is_speaking = is_speaking
        self._is_listening = is_listening

        # Simple FFT for spectrum (placeholder)
        if samples:
            import numpy as np
            fft = np.fft.rfft(samples)
            self._spectrum = np.abs(fft[:50]).tolist()

    def get_data(self) -> dict:
        return {
            "waveform": self._waveform,
            "spectrum": self._spectrum,
            "is_speaking": self._is_speaking,
            "is_listening": self._is_listening,
        }


# ── HUD Manager ───────────────────────────────────────────────────────────────

class InteractiveHUD:
    """
    Enhanced interactive HUD with widget system.

    Features:
    - Multiple widget types with independent refresh
    - Draggable, resizable, click-through widgets
    - Plugin system for custom widgets
    - Integration with all KD subsystems
    - Persistent layout configuration
    """

    def __init__(self, qt_parent=None):
        self._qt_parent = qt_parent
        self._widgets: dict[str, WidgetState] = {}
        self._providers = {
            "metrics": MetricsProvider(),
            "task_progress": TaskProgressProvider(),
            "speaker": SpeakerProvider(),
            "window_context": WindowContextProvider(),
            "voice_visualizer": VoiceVisualizerProvider(),
        }
        self._lock = threading.RLock()
        self._running = False
        self._update_thread: threading.Thread | None = None
        self._awareness = None
        self._window_manager = None
        self._orchestrator = None
        self._voice_processor = None

        # Layout persistence
        base = Path(__file__).resolve().parent.parent
        self._layout_file = base / "config" / "hud_layout.json"

        # Callbacks for UI updates
        self._ui_update_callback: Callable[[dict], None] | None = None

    def initialize(self, qt_parent=None, tool_runner=None) -> bool:
        """Initialize the HUD with all integrations."""
        if self._running:
            return True
        if not is_enabled("INTERACTIVE_HUD"):
            logger.info("Interactive HUD not initialized: flag is off")
            return False

        if qt_parent:
            self._qt_parent = qt_parent

        try:
            # Connect to awareness engine
            if is_enabled("REALTIME_AWARENESS"):
                self._awareness = get_awareness_engine()
                if not self._awareness._started:
                    self._awareness.start()

            # Connect to window manager
            if is_enabled("DYNAMIC_WINDOWS"):
                from core.window_manager import get_window_manager
                self._window_manager = get_window_manager()
                if self._window_manager:
                    self._window_manager.start()

            # Connect to task orchestrator
            if is_enabled("TASK_ORCHESTRATION"):
                from core.task_orchestration import get_task_orchestrator
                self._orchestrator = get_task_orchestrator(tool_runner)

            # Connect to multi-person voice
            if is_enabled("MULTI_PERSON_VOICE"):
                from core.multi_person_voice import get_multi_person_voice
                self._voice_processor = get_multi_person_voice()

            # Create default widgets
            self._create_default_widgets()

            # Load layout
            self._load_layout()

            # Start update loop
            self._running = True
            self._update_thread = threading.Thread(
                target=self._update_loop, daemon=True, name="HUDUpdater"
            )
            self._update_thread.start()

            logger.info("Interactive HUD initialized")
            return True
        except Exception as e:
            logger.warning(f"Interactive HUD initialization failed: {e}")
            return False

    def _create_default_widgets(self) -> None:
        """Create default widget configurations."""
        defaults = [
            WidgetConfig(
                widget_id="metrics_main",
                widget_type=WidgetType.METRICS,
                title="System Metrics",
                position="top-right",
                size=(320, 240),
                refresh_interval=1.0,
            ),
            WidgetConfig(
                widget_id="task_progress_main",
                widget_type=WidgetType.TASK_PROGRESS,
                title="Active Task",
                position="top-left",
                size=(400, 100),
                refresh_interval=0.5,
            ),
            WidgetConfig(
                widget_id="speaker_main",
                widget_type=WidgetType.SPEAKER_ID,
                title="Speaker",
                position="bottom-left",
                size=(250, 80),
                refresh_interval=0.5,
            ),
            WidgetConfig(
                widget_id="window_context_main",
                widget_type=WidgetType.WINDOW_CONTEXT,
                title="Window Context",
                position="bottom-right",
                size=(350, 120),
                refresh_interval=1.0,
            ),
        ]

        for config in defaults:
            self._widgets[config.widget_id] = WidgetState(config=config)

    def _load_layout(self) -> None:
        """Load widget layout from config."""
        import json
        if not self._layout_file.exists():
            return
        try:
            data = json.loads(self._layout_file.read_text())
            for widget_data in data.get("widgets", []):
                widget_id = widget_data.get("widget_id")
                if widget_id in self._widgets:
                    config = self._widgets[widget_id].config
                    # Update config with saved values
                    for key, value in widget_data.items():
                        if hasattr(config, key) and key != "widget_type":
                            setattr(config, key, value)
        except Exception as e:
            logger.warning(f"Failed to load HUD layout: {e}")

    def _save_layout(self) -> None:
        """Save widget layout to config."""
        import json
        try:
            data = {
                "widgets": [
                    {
                        "widget_id": w.config.widget_id,
                        "widget_type": w.config.widget_type.value,
                        "title": w.config.title,
                        "enabled": w.config.enabled,
                        "position": w.config.position,
                        "size": list(w.config.size),
                        "refresh_interval": w.config.refresh_interval,
                        "opacity": w.config.opacity,
                        "click_through": w.config.click_through,
                        "draggable": w.config.draggable,
                    }
                    for w in self._widgets.values()
                ]
            }
            self._layout_file.parent.mkdir(parents=True, exist_ok=True)
            self._layout_file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save HUD layout: {e}")

    def _update_loop(self) -> None:
        """Background update loop for all widgets."""
        last_updates: dict[str, float] = {}

        while self._running:
            now = time.time()

            # Update providers
            self._update_providers()

            # Update widgets that are due
            for widget_id, widget in self._widgets.items():
                if not widget.config.enabled or not widget.visible:
                    continue

                interval = widget.config.refresh_interval
                last = last_updates.get(widget_id, 0)
                if now - last >= interval:
                    self._update_widget(widget_id, widget)
                    last_updates[widget_id] = now

            # Push to UI if callback registered
            if self._ui_update_callback:
                self._push_ui_update()

            time.sleep(0.1)  # 10Hz loop

    def _update_providers(self) -> None:
        """Update all data providers."""
        # Metrics
        metrics_data = self._providers["metrics"].collect()

        # Task progress
        if self._orchestrator:
            self._providers["task_progress"].update_from_orchestrator(self._orchestrator)

        # Speaker
        if self._awareness:
            self._providers["speaker"].update_from_awareness(self._awareness)

        # Window context
        if self._window_manager:
            self._providers["window_context"].update_from_window_manager(self._window_manager)

    def _update_widget(self, widget_id: str, widget: WidgetState) -> None:
        """Update a single widget's data."""
        try:
            widget_type = widget.config.widget_type

            if widget_type == WidgetType.METRICS:
                widget.data = self._providers["metrics"].collect()
            elif widget_type == WidgetType.TASK_PROGRESS:
                widget.data = self._providers["task_progress"].get_data()
            elif widget_type == WidgetType.SPEAKER_ID:
                widget.data = self._providers["speaker"].get_data()
            elif widget_type == WidgetType.WINDOW_CONTEXT:
                widget.data = self._providers["window_context"].get_data()
            elif widget_type == WidgetType.VOICE_VISUALIZER:
                widget.data = self._providers["voice_visualizer"].get_data()
            elif widget_type == WidgetType.CUSTOM:
                # Custom widgets get their data from custom_data or callbacks
                pass

            widget.last_update = time.time()
            widget.error = None
        except Exception as e:
            widget.error = str(e)
            logger.debug(f"Widget {widget_id} update error: {e}")

    def _push_ui_update(self) -> None:
        """Push widget updates to UI callback."""
        try:
            update_data = {}
            for widget_id, widget in self._widgets.items():
                if widget.config.enabled and widget.visible:
                    update_data[widget_id] = {
                        "config": {
                            "widget_id": widget.config.widget_id,
                            "widget_type": widget.config.widget_type.value,
                            "title": widget.config.title,
                            "position": widget.config.position,
                            "size": list(widget.config.size),
                            "opacity": widget.config.opacity,
                            "click_through": widget.config.click_through,
                        },
                        "data": widget.data,
                        "error": widget.error,
                    }
            self._ui_update_callback(update_data)
        except Exception as e:
            logger.debug(f"UI update callback error: {e}")

    def set_ui_update_callback(self, callback: Callable[[dict], None]) -> None:
        """Set callback for UI updates (called from update thread)."""
        self._ui_update_callback = callback

    # ── Widget Management ────────────────────────────────────────────────────

    def add_widget(self, config: WidgetConfig) -> None:
        """Add a new widget."""
        with self._lock:
            self._widgets[config.widget_id] = WidgetState(config=config)
            self._save_layout()

    def remove_widget(self, widget_id: str) -> bool:
        """Remove a widget."""
        with self._lock:
            if widget_id in self._widgets:
                del self._widgets[widget_id]
                self._save_layout()
                return True
            return False

    def update_widget_config(self, widget_id: str, **kwargs) -> bool:
        """Update widget configuration."""
        with self._lock:
            widget = self._widgets.get(widget_id)
            if not widget:
                return False
            for key, value in kwargs.items():
                if hasattr(widget.config, key):
                    setattr(widget.config, key, value)
            self._save_layout()
            return True

    def get_widget(self, widget_id: str) -> WidgetState | None:
        """Get widget state."""
        with self._lock:
            return self._widgets.get(widget_id)

    def list_widgets(self) -> list[WidgetState]:
        """List all widgets."""
        with self._lock:
            return list(self._widgets.values())

    def toggle_widget(self, widget_id: str) -> bool:
        """Toggle widget visibility."""
        with self._lock:
            widget = self._widgets.get(widget_id)
            if widget:
                widget.visible = not widget.visible
                return True
            return False

    # ── Voice Visualizer Integration ─────────────────────────────────────────

    def update_voice_audio(self, samples: list[float], is_speaking: bool = False,
                          is_listening: bool = False) -> None:
        """Update voice visualizer with audio data."""
        self._providers["voice_visualizer"].update_audio(samples, is_speaking, is_listening)

    # ── Awareness Engine Event Integration ───────────────────────────────────

    def handle_event(self, event_type: str, payload: dict) -> None:
        """Handle events from awareness engine for immediate UI updates."""
        if event_type == EventType.HUD_TASK_MODE:
            # Task mode changed - could trigger widget highlight
            pass
        elif event_type == EventType.VOICE_SPEAKER_CHANGED:
            # Speaker changed - update immediately
            self._update_widget("speaker_main", self._widgets.get("speaker_main", WidgetState(config=WidgetConfig(
                widget_id="speaker_main", widget_type=WidgetType.SPEAKER_ID, title="Speaker"
            ))))
        elif event_type == EventType.WINDOW_FOCUS:
            # Window focus changed
            self._update_widget("window_context_main", self._widgets.get("window_context_main", WidgetState(config=WidgetConfig(
                widget_id="window_context_main", widget_type=WidgetType.WINDOW_CONTEXT, title="Window Context"
            ))))

    # ── Layout Presets ────────────────────────────────────────────────────────

    def apply_preset(self, preset: str) -> None:
        """Apply a layout preset."""
        presets = {
            "minimal": {
                "metrics_main": {"enabled": True, "position": "top-right", "size": (200, 150)},
                "task_progress_main": {"enabled": False},
                "speaker_main": {"enabled": False},
                "window_context_main": {"enabled": False},
            },
            "full": {
                "metrics_main": {"enabled": True, "position": "top-right", "size": (320, 240)},
                "task_progress_main": {"enabled": True, "position": "top-left", "size": (400, 100)},
                "speaker_main": {"enabled": True, "position": "bottom-left", "size": (250, 80)},
                "window_context_main": {"enabled": True, "position": "bottom-right", "size": (350, 120)},
            },
            "coding": {
                "metrics_main": {"enabled": True, "position": "top-right", "size": (280, 200)},
                "task_progress_main": {"enabled": True, "position": "top-left", "size": (500, 120)},
                "speaker_main": {"enabled": False},
                "window_context_main": {"enabled": True, "position": "bottom-right", "size": (300, 100)},
            },
        }

        if preset in presets:
            for widget_id, config in presets[preset].items():
                if widget_id in self._widgets:
                    for key, value in config.items():
                        setattr(self._widgets[widget_id].config, key, value)
            self._save_layout()

    # ── Shutdown ──────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """Clean shutdown."""
        self._running = False
        if self._update_thread:
            self._update_thread.join(timeout=2.0)
        self._save_layout()
        logger.info("Interactive HUD shutdown")


# ── Qt Integration Helper ────────────────────────────────────────────────────

def create_hud_overlay_widget(parent=None):
    """
    Create a Qt widget for the HUD overlay.

    This is a helper that creates a transparent, click-through,
    always-on-top widget that can host the HUD visualization.
    """
    try:
        from PyQt6.QtCore import Qt, QTimer, QRect
        from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
        from PyQt6.QtGui import QPainter, QColor, QFont, QPen

        class HUDOverlay(QWidget):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.setWindowFlags(
                    Qt.WindowType.FramelessWindowHint |
                    Qt.WindowType.WindowStaysOnTopHint |
                    Qt.WindowType.Tool |
                    Qt.WindowType.WindowTransparentForInput
                )
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                self.resize(1920, 1080)  # Full screen
                self._widget_data = {}

            def update_data(self, data: dict):
                self._widget_data = data
                self.update()

            def paintEvent(self, event):
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)

                # Draw each widget
                for widget_id, widget in self._widget_data.items():
                    config = widget.get("config", {})
                    wdata = widget.get("data", {})

                    x, y = _hud_get_position(self, config.get("position", "top-right"), config.get("size", [300, 200]))
                    w, h = config.get("size", [300, 200])
                    opacity = config.get("opacity", 0.9)

                    # Draw widget background
                    painter.setOpacity(opacity)
                    painter.fillRect(x, y, w, h, QColor(0, 10, 20, 200))
                    painter.setPen(QPen(QColor(0, 200, 255), 1))
                    painter.drawRect(x, y, w, h)

                    # Draw title
                    painter.setPen(QColor(0, 229, 255))
                    painter.setFont(QFont("Consolas", 10))
                    painter.drawText(x + 10, y + 20, config.get("title", widget_id))

                    # Draw widget-specific content
                    _hud_draw_widget_content(self, painter, x, y, w, h, config.get("widget_type"), wdata)

        return HUDOverlay(parent)
    except ImportError:
        logger.warning("PyQt6 not available for HUD overlay")
        return None


# ── Helper functions for HUD overlay (defined at module level) ──────────────

def _hud_get_position(self, position: str, size: list[int]) -> tuple[int, int]:
    """Calculate widget position based on preset."""
    w, h = size
    sw, sh = self.width(), self.height()
    margin = 20

    if position == "top-right":
        return (sw - w - margin, margin)
    elif position == "top-left":
        return (margin, margin)
    elif position == "bottom-right":
        return (sw - w - margin, sh - h - margin)
    elif position == "bottom-left":
        return (margin, sh - h - margin)
    elif position == "center":
        return ((sw - w) // 2, (sh - h) // 2)
    return (margin, margin)


def _hud_draw_widget_content(self, painter, x, y, w, h, widget_type, data):
    """Draw widget-specific content."""
    # Qt is imported inside create_hud_overlay_widget() so that this module
    # stays importable without PyQt; the drawing helpers therefore import the
    # QtGui names they need here rather than relying on module globals.
    from PyQt6.QtGui import QColor, QFont, QPen

    painter.setFont(QFont("Consolas", 9))
    painter.setPen(QColor(176, 252, 255))

    if widget_type == "metrics":
        cpu = data.get("cpu", 0)
        mem = data.get("memory", 0)
        gpu = data.get("gpu")
        painter.drawText(x + 10, y + 40, f"CPU: {cpu:.1f}%")
        painter.drawText(x + 10, y + 60, f"RAM: {mem:.1f}%")
        if gpu is not None:
            painter.drawText(x + 10, y + 80, f"GPU: {gpu:.1f}%")

    elif widget_type == "task_progress":
        name = data.get("name", "No active task")
        progress = data.get("progress", 0)
        status = data.get("status", "idle")
        painter.drawText(x + 10, y + 40, f"{name}")
        painter.drawText(x + 10, y + 60, f"Status: {status}  Progress: {progress*100:.0f}%")
        # Progress bar
        painter.setPen(QPen(QColor(0, 229, 255), 2))
        painter.drawRect(x + 10, y + 70, w - 20, 15)
        painter.fillRect(x + 12, y + 72, int((w - 24) * progress), 11, QColor(0, 229, 255, 180))

    elif widget_type == "speaker_id":
        name = data.get("speaker_name", "No speaker")
        conf = data.get("confidence", 0)
        speaking = data.get("is_speaking", False)
        color = QColor(0, 255, 153) if speaking else QColor(176, 252, 255)
        painter.setPen(color)
        painter.drawText(x + 10, y + 40, f"🎤 {name}")
        painter.drawText(x + 10, y + 60, f"Confidence: {conf*100:.0f}%")

    elif widget_type == "window_context":
        title = data.get("title", "No window")
        app = data.get("app_name", "")
        painter.drawText(x + 10, y + 40, f"🪟 {title[:50]}")
        painter.drawText(x + 10, y + 60, f"App: {app}")


# ── Singleton ────────────────────────────────────────────────────────────────

_hud: InteractiveHUD | None = None


def get_interactive_hud(qt_parent=None, tool_runner=None) -> InteractiveHUD | None:
    """Get or create the global interactive HUD."""
    global _hud
    if not is_enabled("INTERACTIVE_HUD"):
        return None
    if _hud is None:
        _hud = InteractiveHUD(qt_parent)
        _hud.initialize(qt_parent, tool_runner)
    return _hud