"""Synthetic camera ownership tests; no physical capture."""
from unittest.mock import patch

import pytest

from core.camera import open_camera


def test_consumers_share_handle_and_last_close_releases():
    with patch("cv2.VideoCapture") as factory:
        cap = factory.return_value
        cap.isOpened.return_value = True
        cap.read.return_value = (True, "synthetic frame")
        preview = open_camera(97)
        gesture = open_camera(97)
        snapshot = open_camera(97)
        try:
            factory.assert_called_once()
            preview.release()
            preview.release()
            cap.release.assert_not_called()
            assert gesture.read() == (True, "synthetic frame")
            gesture.release()
            cap.release.assert_not_called()
        finally:
            preview.release()
            gesture.release()
            snapshot.release()
        cap.release.assert_called_once()
        assert not snapshot.isOpened()
        assert snapshot.read() == (False, None)


def test_failed_open_is_not_cached():
    with patch("cv2.VideoCapture") as factory:
        factory.return_value.isOpened.return_value = False
        for _ in range(2):
            with pytest.raises(RuntimeError, match="Cannot open camera"):
                open_camera(98)
        assert factory.call_count == 2
        assert factory.return_value.release.call_count == 2