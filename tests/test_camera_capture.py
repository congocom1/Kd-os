"""Camera failure handling without accessing hardware or user configuration."""
from unittest.mock import MagicMock, patch

import pytest

from actions import screen_processor as camera


@pytest.mark.parametrize("opened", [False, True])
def test_capture_releases_on_failure(opened):
    cap = MagicMock()
    cap.isOpened.return_value = opened
    cap.read.side_effect = RuntimeError("read failed")
    with patch.object(camera, "_CV2", True), \
         patch.object(camera, "_get_camera_index", return_value=0), \
         patch.object(camera, "_cv2_backend", return_value=0), \
         patch("core.camera.open_camera", return_value=cap):
        with pytest.raises(RuntimeError, match="read failed" if opened else "gesture control"):
            camera._capture_camera()
    cap.release.assert_called_once()


def test_detection_failure_does_not_persist_default():
    with patch.object(camera, "_cv2_backend", return_value=0), \
         patch.object(camera, "_probe_camera", return_value=False), \
         patch.object(camera, "_save_config_key") as save:
        with pytest.raises(RuntimeError, match="No usable camera"):
            camera._detect_camera_index()
        save.assert_not_called()


def test_probe_releases_on_read_exception():
    with patch.object(camera, "_CV2", True), patch.object(camera, "cv2") as cv:
        cap = cv.VideoCapture.return_value
        cap.isOpened.return_value = True
        cap.read.side_effect = RuntimeError("read failed")
        with pytest.raises(RuntimeError, match="read failed"):
            camera._probe_camera(0, 0)
        cap.release.assert_called_once()