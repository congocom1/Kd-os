# people_recognition.py
# Face and people detection from the webcam for JARVIS.
#
# Captures a camera frame and runs OpenCV Haar-cascade face detection, then
# reports how many people/faces are visible and where. This is local, private
# computer vision — no images leave the machine.
#
# Auto-discovered by core/action_loader via the TOOL dict below.

from __future__ import annotations

import os as _os
import sys
from pathlib import Path

from core import outcome
from core.lazyimport import LazyModule, installed

# OpenCV is imported on first USE, never at launch — see core/lazyimport.py.
_CV2 = installed("cv2")
cv2 = LazyModule("cv2")

try:
    import numpy as np
    _NP = True
except ImportError:  # pragma: no cover — numpy is a core dependency
    np = None  # type: ignore[assignment]
    _NP = False


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


# Haar cascade XML files ship with OpenCV. We locate and load them at first use.
_FACE_CASCADE = None
_FACE_CASCADE_TRIED = False


def _face_cascade():
    """Load the OpenCV frontal-face Haar cascade, resolving its path."""
    global _FACE_CASCADE, _FACE_CASCADE_TRIED
    if not _CV2:
        return None
    if _FACE_CASCADE_TRIED:
        return _FACE_CASCADE  # may be None if not found
    _FACE_CASCADE_TRIED = True
    candidates = [
        _os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml"),
        _os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_alt.xml"),
    ]
    for path in candidates:
        if _os.path.exists(path):
            _FACE_CASCADE = cv2.CascadeClassifier(path)
            return _FACE_CASCADE
    _FACE_CASCADE = None
    return None


def _capture_frame(camera_index: int = 0):
    """Open the webcam, capture one frame, return (frame, ok)."""
    if not _CV2 or not _NP:
        return None, False
    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
    cap = cv2.VideoCapture(camera_index, backend)
    if not cap.isOpened():
        cap.release()
        return None, False
    # Warm up — first frames are often underexposed.
    for _ in range(5):
        cap.read()
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        return None, False
    return frame, True


def _detect_faces(frame):
    """Run face detection on a frame. Returns (count, boxes, error_message)."""
    cascade = _face_cascade()
    if cascade is None:
        return 0, [], "face detection unavailable (OpenCV cascade not found)"

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)

    faces = cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(60, 60),
        flags=cv2.CASCADE_SCALE_IMAGE,
    )

    boxes = []
    for (x, y, w, h) in faces:
        boxes.append({"x": int(x), "y": int(y), "w": int(w), "h": int(h)})

    return len(boxes), boxes, None


def people_recognition(parameters: dict, player=None, session_memory=None) -> str:
    """Detect people (faces) in the webcam frame.

    Parameters:
        camera_index: Which webcam to use (default: 0)
        annotate:     Whether to save an annotated frame with boxes (default: false)
    """
    if not _CV2:
        return outcome.failed(
            "people_recognition",
            "OpenCV (cv2) is not installed. Run: pip install opencv-python",
        )

    camera_index = int(parameters.get("camera_index", 0))
    annotate = bool(parameters.get("annotate", False))

    frame, ok = _capture_frame(camera_index)
    if not ok:
        return outcome.failed(
            "people_recognition",
            f"could not open camera index {camera_index}",
            camera_index=camera_index,
        )

    count, boxes, error = _detect_faces(frame)
    if error:
        return outcome.failed("people_recognition", error, camera_index=camera_index)

    if annotate and _NP and boxes:
        out_dir = _base_dir() / "memory" / "captures"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"people_{camera_index}.jpg"
        for b in boxes:
            cv2.rectangle(
                frame,
                (b["x"], b["y"]),
                (b["x"] + b["w"], b["y"] + b["h"]),
                (0, 255, 0),
                3,
            )
        cv2.imwrite(str(out_path), frame)
        if player:
            try:
                player.write_log(f"JARVIS: Annotated people frame saved to {out_path}")
            except Exception:
                pass

    if count == 0:
        return outcome.done(
            "people_recognition",
            people=0,
            camera_index=camera_index,
            faces=[],
            message="no people detected",
        )

    return outcome.done(
        "people_recognition",
        people=count,
        camera_index=camera_index,
        faces=boxes,
    )


# ── Tool declaration (auto-discovered by core/action_loader.py) ───────────────

TOOL = {
    "name": "people_recognition",
    "description": (
        "Detect people (faces) in the webcam camera frame using local OpenCV "
        "face detection. Returns how many people are visible and where. "
        "No images leave the machine — detection runs entirely on-device."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "camera_index": {
                "type": "INTEGER",
                "description": "Which webcam to use (default: 0)",
            },
            "annotate": {
                "type": "BOOLEAN",
                "description": "Save an annotated frame with detection boxes (default: false)",
            },
        },
        "required": [],
    },
    "handler": people_recognition,
}
