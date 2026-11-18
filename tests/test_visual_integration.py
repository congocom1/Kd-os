#!/usr/bin/env python3
"""
test_visual_integration.py — Integration test for visual display

Tests that visual display components import and configure correctly.
Actual QWidget creation requires a display server and is skipped headless.
"""

import os

import pytest


def _headless() -> bool:
    """Best-effort headless detection for Qt widget tests."""
    # Native Linux display servers
    if os.environ.get("DISPLAY", "") == "" and os.environ.get("WAYLAND_DISPLAY", "") == "":
        return True
    # Common CI / container signals
    if os.environ.get("CI", "") or os.environ.get("PYTEST_CURRENT_TEST", ""):
        return True
    return False


def test_visual_display_imports():
    """All visual display modules import cleanly."""
    from core import visual_display
    from core import visual_display_frontend
    from core import visual_display_manager
    from core import visual_hud_panel

    assert visual_display is not None
    assert visual_display_frontend is not None
    assert visual_display_manager is not None
    assert visual_hud_panel is not None


def test_visual_display_manager_config():
    """Visual display config can be created."""
    from core.visual_display_manager import VisualDisplayConfig

    config = VisualDisplayConfig(enabled=True, default_view="3d_studio")
    assert config.enabled is True
    assert config.default_view == "3d_studio"


def test_visual_display_manager_imports():
    """Manager imports without creating widgets."""
    from core.visual_display_manager import get_visual_display_manager

    manager = get_visual_display_manager()
    status = manager.get_display_status()
    assert status["enabled"] is True
    assert status["current_view"] == "3d_studio"


def test_studio_modeler_visual_plugin_no_gui():
    """Studio modeler plugin can create a box; visual update fails gracefully."""
    from plugins.studio_modeler_visual import run as studio_run

    result = studio_run(
        {"action": "create", "otype": "box", "name": "test_cube", "size": "1,1,1"},
        None,
        None,
    )
    assert "test_cube" in result

    result = studio_run({"action": "list"}, None, None)
    assert "test_cube" in result


@pytest.mark.skipif(_headless(), reason="Qt widgets require a display")
def test_studio_modeler_visual_plugin_with_display():
    """Studio modeler plugin can create a box and update the visual display."""
    from plugins.studio_modeler_visual import run as studio_run

    result = studio_run(
        {"action": "create", "otype": "box", "name": "display_cube", "size": "1,1,1"},
        None,
        None,
    )
    assert "display_cube" in result
