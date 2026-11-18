"""core/cinematic_theme.py — Cinematic HUD theme engine.

Provides predefined palettes, global QSS generation, and helpers to apply a
unified cinematic look across the JARVIS Qt interface.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from core.paths import get_base_dir as _get_base_dir

logger = logging.getLogger("jarvis.theme")

BASE_DIR = _get_base_dir()
CONFIG_DIR = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "cinematic_theme.json"

PALETTES: dict[str, dict[str, str]] = {
    "jarvis": {
        "name": "JARVIS Orange",
        "accent": "#ff9500",
        "accent_dim": "#b36a00",
        "accent_ghost": "#2a1a00",
        "bg": "#050403",
        "panel": "rgba(16, 10, 2, 235)",
        "text": "#ffe9c9",
        "text_dim": "#a8834f",
        "border": "#4a2e00",
        "border_bright": "#ff9500",
        "danger": "#ff3355",
        "warning": "#ffcc00",
        "success": "#7fd4ff",
        "holo": "#ffb84d",
        "reactor_core": "#cfe9ff",
        "reactor_housing": "#c9a227",
    },
    "ironman": {
        "name": "Iron Man",
        "accent": "#ffd34d",
        "accent_dim": "#b8860b",
        "accent_ghost": "#2a1e00",
        "bg": "#050608",
        "panel": "rgba(12, 10, 6, 235)",
        "text": "#fff7e0",
        "text_dim": "#a8905c",
        "border": "#3d2e00",
        "border_bright": "#ffd34d",
        "danger": "#ff3355",
        "warning": "#ffaa00",
        "success": "#7fd4ff",
        # Reactor plasma is blue-white against the gold housing.
        "holo": "#7fd4ff",
        "reactor_core": "#bfe9ff",
        "reactor_housing": "#c9a227",
    },
    "tron": {
        "name": "TRON Cyan",
        "accent": "#00e5ff",
        "accent_dim": "#0088aa",
        "accent_ghost": "#001a2e",
        "bg": "#00070a",
        "panel": "rgba(0, 10, 16, 235)",
        "text": "#e0f7ff",
        "text_dim": "#7a9aa6",
        "border": "#003340",
        "border_bright": "#00e5ff",
        "danger": "#ff3355",
        "warning": "#ffaa00",
        "success": "#00ff9d",
    },
    "amber": {
        "name": "Amber Terminal",
        "accent": "#ffb000",
        "accent_dim": "#aa6f00",
        "accent_ghost": "#2a1a00",
        "bg": "#0a0500",
        "panel": "rgba(16, 10, 0, 235)",
        "text": "#fff4d9",
        "text_dim": "#a68b5b",
        "border": "#403000",
        "border_bright": "#ffb000",
        "danger": "#ff4d4d",
        "warning": "#ffcc00",
        "success": "#77ff00",
    },
    "alert": {
        "name": "Red Alert",
        "accent": "#ff3355",
        "accent_dim": "#aa1133",
        "accent_ghost": "#2a0008",
        "bg": "#0a0002",
        "panel": "rgba(16, 0, 4, 235)",
        "text": "#ffe0e6",
        "text_dim": "#a67a82",
        "border": "#400010",
        "border_bright": "#ff3355",
        "danger": "#ff3355",
        "warning": "#ffaa00",
        "success": "#00ff77",
    },
    "stealth": {
        "name": "Stealth Green",
        "accent": "#00ff9d",
        "accent_dim": "#00aa66",
        "accent_ghost": "#001a10",
        "bg": "#000a05",
        "panel": "rgba(0, 16, 10, 235)",
        "text": "#e0fff2",
        "text_dim": "#7aa692",
        "border": "#004020",
        "border_bright": "#00ff9d",
        "danger": "#ff3355",
        "warning": "#ffcc00",
        "success": "#00ff9d",
    },
}

DEFAULT_PALETTE = "jarvis"


def _ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_palette() -> dict[str, str]:
    """Return the saved palette or the default TRON palette."""
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            name = data.get("palette", DEFAULT_PALETTE)
            if name in PALETTES:
                return PALETTES[name]
        except Exception as exc:
            logger.warning("Could not read cinematic theme config: %s", exc)
    return PALETTES[DEFAULT_PALETTE]


def current_palette_name() -> str:
    """The saved palette name, or the default."""
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            name = data.get("palette", DEFAULT_PALETTE)
            if name in PALETTES:
                return name
        except Exception:
            pass
    return DEFAULT_PALETTE


def save_palette(name: str) -> None:
    """Persist the chosen palette name."""
    _ensure_config_dir()
    CONFIG_FILE.write_text(json.dumps({"palette": name}, indent=2), encoding="utf-8")


def get_palette_names() -> list[str]:
    return list(PALETTES.keys())


def get_palette(name: str) -> dict[str, str]:
    if name not in PALETTES:
        name = DEFAULT_PALETTE
    return PALETTES[name]


def _hex_rgb(h: str) -> tuple[int, int, int]:
    h = (h or "#000000").lstrip("#")
    if len(h) != 6:
        return (0, 0, 0)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _tint(h: str, alpha: int) -> str:
    """rgba() string from a hex colour — palette-true translucent tints."""
    r, g, b = _hex_rgb(h)
    return f"rgba({r}, {g}, {b}, {alpha})"


def global_qss(palette: dict[str, str] | None = None) -> str:
    """Return a global Qt stylesheet for a cinematic HUD look."""
    p = palette or load_palette()
    accent = p["accent"]
    accent_dim = p["accent_dim"]
    bg = p["bg"]
    panel = p["panel"]
    text = p["text"]
    text_dim = p["text_dim"]
    border = p["border"]
    border_bright = p["border_bright"]
    danger = p["danger"]
    warning = p["warning"]
    success = p["success"]

    # Translucent surfaces derived from the palette (never hardcoded hues, so
    # every palette — Iron Man gold, TRON cyan — gets a coherent glass look).
    btn_top = _tint(accent, 55)
    btn_bot = _tint(accent, 28)
    btn_top_h = _tint(accent, 95)
    btn_bot_h = _tint(accent, 50)
    input_bg = _tint(bg, 200)
    well_bg = _tint(accent, 18)
    header_bg = _tint(accent, 26)

    return f"""
    /* -- Global cinematic theme -- */
    QWidget {{
        background: {bg};
        color: {text};
        font-family: "Rajdhani", "Orbitron", "Segoe UI", "Noto Sans", sans-serif;
        font-size: 10pt;
        selection-background-color: {accent_dim};
        selection-color: {text};
        outline: none;
    }}

    QMainWindow {{
        background: {bg};
        border: 1px solid {border};
        border-radius: 8px;
    }}

    QToolTip {{
        background: {bg};
        color: {accent};
        border: 1px solid {border_bright};
        padding: 4px 8px;
        border-radius: 3px;
    }}

    /* -- Panels / Cards -- */
    QFrame, QGroupBox, QTextEdit, QPlainTextEdit, QListWidget, QTreeWidget, QTableWidget, QScrollArea {{
        background: {panel};
        border: 1px solid {border};
        border-radius: 6px;
        padding: 6px;
    }}
    QFrame::pane, QGroupBox::pane {{
        border: none;
        background: transparent;
    }}

    QTextEdit, QPlainTextEdit {{
        border: 1px solid {border};
    }}
    QTextEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid {accent};
    }}

    /* -- Buttons -- */
    QPushButton {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {btn_top}, stop:1 {btn_bot});
        color: {text};
        border: 1px solid {border};
        border-radius: 4px;
        padding: 6px 14px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {btn_top_h}, stop:1 {btn_bot_h});
        border: 1px solid {accent};
        color: {accent};
    }}
    QPushButton:pressed {{
        background: {accent_dim};
        color: {bg};
    }}
    QPushButton:disabled {{
        background: rgba(20, 20, 20, 120);
        color: {text_dim};
        border: 1px solid {border};
    }}
    QPushButton[cssClass="danger"] {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 rgba(80, 10, 20, 220), stop:1 rgba(40, 5, 10, 220));
        border: 1px solid {danger};
        color: {danger};
    }}
    QPushButton[cssClass="danger"]:hover {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 rgba(120, 20, 35, 240), stop:1 rgba(60, 10, 18, 240));
    }}
    QPushButton[cssClass="success"] {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 rgba(0, 60, 35, 220), stop:1 rgba(0, 30, 18, 220));
        border: 1px solid {success};
        color: {success};
    }}

    /* -- Inputs -- */
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit {{
        background: {input_bg};
        color: {text};
        border: 1px solid {border};
        border-radius: 4px;
        padding: 4px 8px;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {accent};
    }}

    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox::down-arrow {{
        image: none;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 6px solid {accent};
    }}
    QComboBox QAbstractItemView {{
        background: {bg};
        color: {text};
        border: 1px solid {border};
        selection-background-color: {accent_dim};
    }}

    /* -- Checkboxes / Radios -- */
    QCheckBox, QRadioButton {{
        spacing: 8px;
        background: transparent;
    }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        background: {input_bg};
        border: 1px solid {border};
        border-radius: 3px;
    }}
    QRadioButton::indicator {{
        border-radius: 8px;
    }}
    QCheckBox::indicator:checked {{
        background: {accent_dim};
        border: 1px solid {accent};
    }}
    QRadioButton::indicator:checked {{
        background: {accent};
        border: 1px solid {accent};
    }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
        border: 1px solid {accent};
    }}

    /* -- Scrollbars -- */
    QScrollBar:vertical {{
        background: {bg};
        width: 8px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: {accent_dim};
        border-radius: 4px;
        min-height: 20px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {accent};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        background: transparent;
        height: 0px;
    }}
    QScrollBar:horizontal {{
        background: {bg};
        height: 8px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal {{
        background: {accent_dim};
        border-radius: 4px;
        min-width: 20px;
    }}

    /* -- Progress / Sliders -- */
    QProgressBar {{
        background: {well_bg};
        border: 1px solid {border};
        border-radius: 4px;
        text-align: center;
        color: {text};
    }}
    QProgressBar::chunk {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {accent_dim}, stop:1 {accent});
        border-radius: 3px;
    }}

    QSlider::groove:horizontal {{
        height: 4px;
        background: {border};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {accent};
        width: 14px;
        height: 14px;
        margin: -5px 0;
        border-radius: 7px;
        border: 1px solid {border_bright};
    }}
    QSlider::sub-page:horizontal {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {accent_dim}, stop:1 {accent});
        border-radius: 2px;
    }}

    /* -- Tabs -- */
    QTabWidget::pane {{
        background: {panel};
        border: 1px solid {border};
        border-radius: 6px;
    }}
    QTabBar::tab {{
        background: {well_bg};
        color: {text_dim};
        border: 1px solid {border};
        border-bottom: none;
        border-top-left-radius: 4px;
        border-top-right-radius: 4px;
        padding: 6px 14px;
    }}
    QTabBar::tab:selected {{
        background: {accent_dim};
        color: {text};
        border: 1px solid {accent};
        border-bottom: 1px solid {accent_dim};
    }}
    QTabBar::tab:hover {{
        color: {accent};
    }}

    /* -- Menus / Toolbars -- */
    QMenuBar {{
        background: {bg};
        color: {text};
        border-bottom: 1px solid {border};
    }}
    QMenuBar::item:selected {{
        background: {accent_dim};
        color: {text};
    }}
    QMenu {{
        background: {panel};
        color: {text};
        border: 1px solid {border};
    }}
    QMenu::item:selected {{
        background: {accent_dim};
    }}
    QToolBar {{
        background: {bg};
        border: 1px solid {border};
        spacing: 4px;
        padding: 4px;
    }}

    /* -- Headers / Tables -- */
    QHeaderView::section {{
        background: {header_bg};
        color: {accent};
        border: 1px solid {border};
        padding: 4px 8px;
        font-weight: 600;
    }}
    QTableWidget::item:selected {{
        background: {accent_dim};
        color: {text};
    }}
    QTableWidget::item {{
        border: none;
        padding: 4px;
    }}

    /* -- Splitters / Status -- */
    QSplitter::handle {{
        background: {border};
    }}
    QSplitter::handle:hover {{
        background: {accent};
    }}
    QStatusBar {{
        background: {input_bg};
        color: {text_dim};
        border-top: 1px solid {border};
    }}
    QStatusBar::item {{
        border: none;
    }}

    /* -- Dialogs -- */
    QDialog, QMessageBox {{
        background: {bg};
        border: 1px solid {border};
        border-radius: 8px;
    }}

    /* -- Labels / Status -- */
    QLabel {{
        color: {text};
        background: transparent;
    }}
    QLabel[cssClass="hud-title"] {{
        color: {accent};
        font-size: 14pt;
        font-weight: bold;
        letter-spacing: 1px;
    }}
    QLabel[cssClass="hud-dim"] {{
        color: {text_dim};
    }}
    QLabel[cssClass="hud-danger"] {{
        color: {danger};
    }}
    QLabel[cssClass="hud-warning"] {{
        color: {warning};
    }}
    QLabel[cssClass="hud-success"] {{
        color: {success};
    }}
    """


def apply_to_app(app: Any, palette_name: str | None = None) -> dict[str, str]:
    """Apply the cinematic QSS to a QApplication instance."""
    palette = get_palette(palette_name) if palette_name else load_palette()
    app.setStyleSheet(global_qss(palette))
    if palette_name:
        save_palette(palette_name)
    return palette
