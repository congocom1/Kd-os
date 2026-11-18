"""Headless checks for the HUD's compact telemetry and footer layout."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QWidget

import ui


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def shell(app):
    # Exercise the real builders without starting camera, audio or GL services.
    window = ui.MainWindow.__new__(ui.MainWindow)
    QMainWindow.__init__(window)
    yield window
    window.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("width", [480, 660, 1120])
def test_telemetry_fits_center_stage(shell, app, width):
    strip = shell._build_metrics_strip()
    try:
        strip.resize(width, 54)
        strip.show()
        app.processEvents()
        assert strip.width() == width
        bars = [shell._bar_cpu, shell._bar_mem, shell._bar_net,
                shell._bar_gpu, shell._bar_tmp]
        for bar in bars:
            assert bar.isVisible()
            assert strip.rect().contains(bar.geometry())
        for left, right in zip(bars, bars[1:]):
            assert left.geometry().right() < right.geometry().left()
    finally:
        strip.close()
        strip.deleteLater()


def test_footer_fits_minimum_window(shell, app):
    footer = shell._build_footer()
    try:
        footer.resize(ui._MIN_W, 22)
        footer.show()
        app.processEvents()
        assert footer.width() == ui._MIN_W
        layout = footer.layout()
        widgets = [layout.itemAt(i).widget() for i in range(layout.count())
                   if layout.itemAt(i).widget() is not None]
        for widget in widgets:
            assert footer.rect().contains(widget.geometry())
            assert widget.width() >= widget.sizeHint().width()
    finally:
        footer.close()
        footer.deleteLater()


def test_relocated_metrics_still_update(shell, monkeypatch):
    strip = shell._build_metrics_strip()
    footer = shell._build_footer()
    monkeypatch.setattr(ui._metrics, "snapshot", lambda: {
        "cpu": 42, "mem": 64, "net": 0.5, "gpu": -1, "tmp": -1,
    })
    try:
        shell._update_metrics()
        assert shell._bar_cpu._text == "42%"
        assert shell._bar_mem._text == "64%"
        assert shell._bar_net._text == "512KB/s"
        assert shell._bar_gpu._text == "N/A"
        assert shell._bar_tmp._text == "N/A"
        assert "--" not in shell._uptime_lbl.text()
        assert "--" not in shell._proc_lbl.text()
    finally:
        strip.deleteLater()
        footer.deleteLater()


def test_stage_navigation_fits_and_selects(shell, app):
    shell._hud_cam_stack = QStackedWidget(shell)
    for _ in range(5):
        shell._hud_cam_stack.addWidget(QWidget())
    tabs = shell._build_center_tabs()
    try:
        tabs.resize(480, 42)
        tabs.show()
        app.processEvents()
        assert tabs.width() == 480
        for page, button in shell._center_tab_btns.items():
            assert tabs.rect().contains(button.geometry())
            assert button.width() >= button.sizeHint().width()
            assert button.accessibleName()
            button.click()
            assert shell._hud_cam_stack.currentIndex() == page
            assert button.isChecked()
            assert sum(b.isChecked() for b in shell._center_tab_btns.values()) == 1
    finally:
        tabs.close()
        tabs.deleteLater()


def test_gesture_toggle_reports_initialization_failure(shell, monkeypatch):
    from PyQt6.QtWidgets import QCheckBox
    shell._gesture_controller = None
    shell._gesture_toggle = QCheckBox()
    monkeypatch.setattr(ui, 'GESTURE_3D_AVAILABLE', True)
    monkeypatch.setattr(shell, '_init_gesture_controller', lambda: None)
    assert shell.toggle_gesture_control(True) is False
    assert not shell._gesture_toggle.isChecked()


def test_gesture_dispatch_only_when_enabled(shell):
    from unittest.mock import Mock
    shell._gesture_controller = Mock()
    shell._gesture_target = Mock()
    shell._gesture_controller.status.return_value = {'enabled': False}
    shell._dispatch_gesture('rotate', (1., 2.))
    shell._gesture_target.gesture_rotate.assert_not_called()
    shell._gesture_controller.status.return_value = {'enabled': True}
    shell._dispatch_gesture('rotate', (1., 2.))
    shell._gesture_target.gesture_rotate.assert_called_once_with(1., 2.)


# ── Media Player Panel tests ─────────────────────────────────────────────

def test_video_player_show_and_stop(app):
    player = ui.VideoPlayerPanel()
    try:
        assert not player.video_is_playing()
        player.show_video("https://example.com/clip.mp4", "Test Clip", muted=True)
        assert player.video_is_playing()
        assert player._video_title == "Test Clip"
        assert player._muted is True
        player.set_video_muted(False)
        assert player._muted is False
        player.stop_video()
        assert not player.video_is_playing()
    finally:
        player.deleteLater()
        app.processEvents()


def test_video_player_request_say(app):
    player = ui.VideoPlayerPanel()
    said = []
    player.request_say_cb = lambda text: said.append(text)
    try:
        player.request_say("Speak this")
        assert said == ["Speak this"]
    finally:
        player.deleteLater()
        app.processEvents()


# ── Actions Panel tests ──────────────────────────────────────────────────

def test_actions_panel_refresh_shows_inventory(app):
    panel = ui.ActionsPanel()
    catalog_called = []
    def fake_catalog():
        catalog_called.append(True)
        return [
            {"name": "calculator", "kind": "plugin", "valid": True, "enabled": True,
             "description": "Evaluates maths", "file": "calculator.py", "error": ""},
            {"name": "broken_tool", "kind": "action", "valid": False, "enabled": False,
             "description": "", "file": "broken.py", "error": "Missing handler"},
            {"name": "system_status", "kind": "core", "valid": True, "enabled": True,
             "description": "System metrics", "file": "main.py", "error": ""},
        ]
    panel.set_feature_catalog(fake_catalog)
    try:
        panel.refresh()
        assert len(catalog_called) >= 1
        assert "3 functions · 2 active" in panel._actions_subtitle.text()
        # Rows: stretch is last, so count - 1
        row_count = panel._actions_layout.count() - 1
        assert row_count == 3
    finally:
        panel.deleteLater()
        app.processEvents()


def test_actions_panel_no_catalog_is_safe(app):
    panel = ui.ActionsPanel()
    try:
        panel.refresh()  # should not raise
        assert "0 functions · 0 active" in panel._actions_subtitle.text()
    finally:
        panel.deleteLater()
        app.processEvents()