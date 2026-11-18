"""Tests for 3D gesture control module."""
import sys
from unittest.mock import MagicMock, patch

import pytest

# Test imports work
from core.gesture_3d import (
    Gesture3DController,
    HandState,
    MediaPipeHandTracker,
    GESTURE_3D_AVAILABLE,
)


def test_gesture_controller_creation():
    """Test that controller can be created and returns status."""
    controller = Gesture3DController()
    status = controller.status()

    assert "enabled" in status
    assert "camera_index" in status
    assert "backend" in status
    assert "callbacks" in status
    assert status["enabled"] is False
    assert status["backend"] == "mediapipe"


def test_gesture_controller_enable_disable():
    """Test enabling and disabling the controller."""
    controller = Gesture3DController()

    # Should not crash when enabling without camera (will fail gracefully)
    # We mock the camera to avoid needing actual hardware
    with patch("core.gesture_3d.MediaPipeHandTracker"), patch("cv2.VideoCapture") as mock_cap:
        mock_cap.return_value.isOpened.return_value = True
        mock_cap.return_value.read.return_value = (False, None)

        controller.enable(True)
        # Note: enable starts a thread, but without proper camera it will exit quickly
        controller.enable(False)

    # Status should reflect disabled state
    assert controller.status()["enabled"] is False


def test_hand_state_dataclass():
    """Test HandState dataclass creation."""
    hand = HandState(
        landmarks=[],
        handedness="Right",
        center_x=0.5,
        center_y=0.5,
        pinch_distance=0.05,
        is_fist=False,
        is_pointing=True,
        is_open_palm=False,
    )
    assert hand.handedness == "Right"
    assert hand.is_pointing is True


def test_gesture_callbacks():
    """Test that callbacks can be set and called."""
    controller = Gesture3DController()

    rotate_calls = []
    zoom_calls = []
    pan_calls = []
    reset_calls = []

    controller.on_rotate = lambda dx, dy: rotate_calls.append((dx, dy))
    controller.on_zoom = lambda d: zoom_calls.append(d)
    controller.on_pan = lambda dx, dy: pan_calls.append((dx, dy))
    controller.on_reset = lambda: reset_calls.append(True)

    status = controller.status()
    assert status["callbacks"]["rotate"] is True
    assert status["callbacks"]["zoom"] is True
    assert status["callbacks"]["pan"] is True
    assert status["callbacks"]["reset"] is True

    # Manually invoke callbacks
    controller.on_rotate(10, 5)
    controller.on_zoom(1.5)
    controller.on_pan(0.1, 0.2)
    controller.on_reset()

    assert rotate_calls == [(10, 5)]
    assert zoom_calls == [1.5]
    assert pan_calls == [(0.1, 0.2)]
    assert reset_calls == [True]


def test_reactor_widget_gesture_available():
    """Test that reactor widget reports gesture availability."""
    from core.reactor_widget import GESTURE_3D_AVAILABLE as REACTOR_GESTURE_AVAILABLE
    # Should match the gesture module's availability
    assert REACTOR_GESTURE_AVAILABLE == GESTURE_3D_AVAILABLE


def test_missing_camera_does_not_enable():
    controller = Gesture3DController()
    with patch('core.gesture_3d.MediaPipeHandTracker') as tracker, patch('cv2.VideoCapture') as cap:
        cap.return_value.isOpened.return_value = False
        with pytest.raises(RuntimeError, match='Cannot open camera'):
            controller.enable(True)
        assert not controller.status()['enabled']
        tracker.return_value.close.assert_called_once()
        cap.return_value.release.assert_called_once()


def test_lost_hands_reset_debounce():
    controller = Gesture3DController()
    controller._gesture_counters['pan'] = 3
    controller._process_gestures([])
    assert not controller._gesture_counters


def test_missing_mediapipe_reports_install_command():
    with patch("core.gesture_3d._MP", False), patch("cv2.VideoCapture") as cap:
        controller = Gesture3DController()
        with pytest.raises(RuntimeError, match="pip install mediapipe") as error:
            controller.enable(True)
        assert sys.executable in str(error.value)
        assert not controller.status()["enabled"]
        cap.assert_not_called()


def test_no_fake_opencv_fallback():
    controller = Gesture3DController(use_mediapipe=False)
    assert controller.status()["backend"] == "unavailable"
    assert not controller.status()["available"]
    with pytest.raises(RuntimeError, match="MediaPipe backend"):
        controller.enable(True)


def test_missing_dependencies_report_unavailable():
    with patch("core.gesture_3d.GESTURE_3D_AVAILABLE", False):
        assert not Gesture3DController().status()["available"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])