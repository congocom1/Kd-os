# gesture_3d.py
# Camera-based 3D model manipulation using MediaPipe hand tracking.
#
# Detects hand gestures from the webcam and maps them to 3D viewer controls:
#   - One hand (index finger extended): orbit/rotate
#   - Two hands (pinch): zoom in/out
#   - Two hands (open palms): pan
#   - Fist (closed hand): reset view
#
# Designed to integrate with ReactorGL widget for the Arc Reactor viewer.

from __future__ import annotations

import math
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from core.lazyimport import LazyModule, installed

# MediaPipe is imported on first use
_MP = installed("mediapipe")
mp = LazyModule("mediapipe")

# OpenCV for camera capture
_CV2 = installed("cv2")
cv2 = LazyModule("cv2")

try:
    import numpy as np
    _NP = True
except ImportError:
    np = None
    _NP = False


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


@dataclass
class HandState:
    """State of a single detected hand."""
    landmarks: list  # 21 MediaPipe hand landmarks
    handedness: str  # "Left" or "Right"
    center_x: float  # Normalized palm center (0-1)
    center_y: float
    pinch_distance: float  # Distance between thumb and index tips (0-1)
    is_fist: bool
    is_pointing: bool  # Index extended, others folded
    is_open_palm: bool


@dataclass
class Gesture3DState:
    """Aggregated gesture state for 3D manipulation."""
    hands: list[HandState]
    rotation_delta: tuple[float, float] = (0.0, 0.0)  # (dx, dy) in degrees
    zoom_delta: float = 0.0  # Positive = zoom in
    pan_delta: tuple[float, float] = (0.0, 0.0)  # (dx, dy) normalized
    reset_requested: bool = False


class MediaPipeHandTracker:
    """MediaPipe-based hand landmark detection using the new Tasks API (MediaPipe >= 0.10)."""

    def __init__(self, max_hands: int = 2, min_detection_confidence: float = 0.7,
                 min_tracking_confidence: float = 0.5, model_path: str | None = None):
        if not _MP:
            raise RuntimeError(
                "MediaPipe is not installed in this Python environment. "
                f'Install it with: "{sys.executable}" -m pip install mediapipe; '
                "then restart JARVIS."
            )
        if not _CV2:
            raise RuntimeError("opencv-python not installed")
        if not _NP:
            raise RuntimeError("numpy not installed")

        # Import the new MediaPipe Tasks vision API
        # Access vision as attribute of mediapipe.tasks (not as submodule)
        import mediapipe.tasks
        vision = mediapipe.tasks.vision
        BaseOptions = mediapipe.tasks.BaseOptions

        self._HandLandmarker = vision.HandLandmarker
        self._HandLandmarkerOptions = vision.HandLandmarkerOptions
        self._BaseOptions = BaseOptions
        self._VisionRunningMode = vision.RunningMode

        # Find or download model file
        if model_path is None:
            model_path = self._find_or_download_model()

        if not model_path or not Path(model_path).exists():
            raise RuntimeError(
                "MediaPipe hand landmarker model not found. "
                "Download 'hand_landmarker.task' from "
                "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task "
                "and place it in the working directory or set GESTURE_3D_MODEL_PATH env var."
            )

        # Create the hand landmarker
        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model_path),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=max_hands,
            min_hand_detection_confidence=min_detection_confidence,
            min_hand_presence_confidence=min_tracking_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)

    def _find_or_download_model(self) -> str | None:
        """Find model file or download it."""
        import os
        from pathlib import Path

        # Check environment variable
        env_path = os.environ.get("GESTURE_3D_MODEL_PATH")
        if env_path and Path(env_path).exists():
            return env_path

        # Check common locations
        common_paths = [
            Path("hand_landmarker.task"),
            Path(__file__).parent / "hand_landmarker.task",
            Path(__file__).parent.parent / "assets" / "hand_landmarker.task",
        ]

        for path in common_paths:
            if path.exists():
                return str(path)

        # Try to download
        try:
            return self._download_model()
        except Exception:
            return None

    def _download_model(self) -> str:
        """Download the hand landmarker model."""
        import urllib.request
        from pathlib import Path

        url = ("https://storage.googleapis.com/mediapipe-models/"
               "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task")
        dest = Path("hand_landmarker.task")

        print(f"[Gesture3D] Downloading hand landmarker model from {url}...")
        urllib.request.urlretrieve(url, dest)
        print(f"[Gesture3D] Model saved to {dest}")
        return str(dest)

    def process(self, frame_bgr: np.ndarray, timestamp_ms: int = 0) -> list[HandState]:
        """Process a BGR frame and return detected hand states."""
        import mediapipe as mp

        # Convert BGR to RGB
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        # Create MediaPipe Image
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)

        # Detect hands
        result = self._landmarker.detect_for_video(mp_image, timestamp_ms)

        hand_states = []
        if result.hand_landmarks:
            for idx, hand_landmarks in enumerate(result.hand_landmarks):
                landmarks = hand_landmarks

                # Get handedness
                handedness_label = "Right"
                if result.handedness and idx < len(result.handedness):
                    handedness_label = result.handedness[idx][0].category_name

                # Calculate palm center (wrist + middle finger MCP average)
                wrist = landmarks[0]
                middle_mcp = landmarks[9]
                center_x = (wrist.x + middle_mcp.x) / 2
                center_y = (wrist.y + middle_mcp.y) / 2

                # Pinch distance (thumb tip to index tip)
                thumb_tip = landmarks[4]
                index_tip = landmarks[8]
                pinch_dist = math.hypot(thumb_tip.x - index_tip.x,
                                        thumb_tip.y - index_tip.y)

                # Finger states
                finger_tips = [4, 8, 12, 16, 20]  # thumb, index, middle, ring, pinky
                finger_pips = [3, 6, 10, 14, 18]  # corresponding PIP joints

                fingers_extended = []
                for tip_idx, pip_idx in zip(finger_tips, finger_pips):
                    # For thumb, compare x; for others, compare y
                    if tip_idx == 4:  # thumb
                        extended = landmarks[tip_idx].x > landmarks[pip_idx].x
                    else:
                        extended = landmarks[tip_idx].y < landmarks[pip_idx].y
                    fingers_extended.append(extended)

                # Gesture classification
                is_fist = not any(fingers_extended)
                is_pointing = (fingers_extended[1] and
                              not any(fingers_extended[2:]))  # only index extended
                is_open_palm = all(fingers_extended)

                hand_states.append(HandState(
                    landmarks=landmarks,
                    handedness=handedness_label,
                    center_x=center_x,
                    center_y=center_y,
                    pinch_distance=pinch_dist,
                    is_fist=is_fist,
                    is_pointing=is_pointing,
                    is_open_palm=is_open_palm,
                ))

        return hand_states

    def draw_landmarks(self, frame_bgr: np.ndarray, hand_states: list[HandState]) -> np.ndarray:
        """Draw hand landmarks on frame for debugging/visualization."""
        if not hand_states:
            return frame_bgr

        # The new API requires drawing on the RGB image
        # For now, return original frame
        return frame_bgr

    def close(self):
        if self._landmarker:
            self._landmarker.close()


class OpenCVHandTracker:
    """Fallback hand tracker using OpenCV skin-color segmentation (legacy)."""

    def __init__(self, camera_index: int = 0):
        if not _CV2:
            raise RuntimeError("opencv-python not installed")
        if not _NP:
            raise RuntimeError("numpy not installed")

        self.camera_index = camera_index
        self.cap = None
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(history=100, varThreshold=50)

    def start(self):
        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open camera {self.camera_index}")

    def process(self, frame_bgr: np.ndarray) -> list[HandState]:
        # Simplified skin-color based detection
        # This is a placeholder; the full implementation is in gesture_control.py
        return []

    def stop(self):
        if self.cap:
            self.cap.release()
            self.cap = None


class Gesture3DController:
    """High-level 3D manipulation controller using hand gestures."""

    def __init__(self, camera_index: int = 0, use_mediapipe: bool = True):
        self.camera_index = camera_index
        self.use_mediapipe = use_mediapipe

        self._tracker: Optional[MediaPipeHandTracker] = None
        self._cv_cap: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._enabled = False

        # Callbacks for 3D manipulation
        self.on_rotate: Optional[Callable[[float, float], None]] = None
        self.on_zoom: Optional[Callable[[float], None]] = None
        self.on_pan: Optional[Callable[[float, float], None]] = None
        self.on_reset: Optional[Callable[[], None]] = None

        # Smoothing
        self._prev_rotation_center: Optional[tuple[float, float]] = None
        self._prev_pinch_distance: Optional[float] = None
        self._prev_pan_center: Optional[tuple[float, float]] = None

        # Sensitivity
        self.rotation_sensitivity = 180.0  # degrees per normalized screen unit
        self.zoom_sensitivity = 5.0
        self.pan_sensitivity = 2.0

        # Stability
        self._gesture_hold_frames = 3
        self._gesture_counters: dict[str, int] = {}

    def _init_tracker(self):
        if self.use_mediapipe:
            self._tracker = MediaPipeHandTracker()
        else:
            raise RuntimeError("Hand gestures require the MediaPipe backend")
        from core.camera import open_camera
        try:
            self._cv_cap = open_camera(self.camera_index)
        except Exception:
            self._release_tracker()
            raise
        if not self._cv_cap.isOpened():
            self._release_tracker()
            raise RuntimeError(f"Cannot open camera {self.camera_index}")

    def _release_tracker(self):
        if self._tracker:
            self._tracker.close()
            self._tracker = None
        if self._cv_cap:
            self._cv_cap.release()
            self._cv_cap = None

    def enable(self, enabled: bool = True):
        if enabled and not self._enabled:
            if self._thread and self._thread.is_alive():
                raise RuntimeError("Previous camera worker is still stopping")
            self._init_tracker()
            self._stop_event.clear()
            self._enabled = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
        elif not enabled and self._enabled:
            self._enabled = False
            self._stop_event.set()
            if self._thread:
                self._thread.join(timeout=2.0)
            self._reset_gesture_state()

    def _run_loop(self):
        try:
            self._run_mediapipe_loop()
        finally:
            self._enabled = False
            self._release_tracker()

    def _run_mediapipe_loop(self):
        cap = self._cv_cap
        if not cap.isOpened():
            print("[Gesture3D] Cannot open camera")
            return

        timestamp_ms = 0
        try:
            while not self._stop_event.is_set():
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.01)
                    continue

                # Mirror for natural interaction
                frame = cv2.flip(frame, 1)

                hand_states = self._tracker.process(frame, timestamp_ms)
                self._process_gestures(hand_states)

                timestamp_ms += 16  # ~60 FPS
                # Small delay to prevent CPU spinning
                time.sleep(0.016)  # ~60 FPS max
        finally:
            # Resources are owned and released by _run_loop's finally block.
            self._stop_event.set()

    def _run_opencv_loop(self):
        # Simplified fallback - would use the existing gesture_control.py logic
        pass

    def _process_gestures(self, hands: list[HandState]):
        """Process detected hands and emit manipulation events."""
        count = len(hands)
        if count != getattr(self, '_previous_hand_count', 0):
            self._reset_gesture_state()
        self._previous_hand_count = count
        if not hands:
            self._reset_gesture_state()
            return

        # Classify gesture based on hand count and states
        if len(hands) == 1:
            self._process_one_hand(hands[0])
        elif len(hands) == 2:
            self._process_two_hands(hands[0], hands[1])

    def _process_one_hand(self, hand: HandState):
        """Single hand gestures: rotate (pointing) or reset (fist)."""
        if hand.is_fist:
            self._increment_counter("fist")
            if self._gesture_counters.get("fist", 0) >= self._gesture_hold_frames:
                if self.on_reset:
                    self.on_reset()
                self._gesture_counters["fist"] = 0
        else:
            self._gesture_counters["fist"] = 0

        if hand.is_pointing:
            self._increment_counter("pointing")
            if self._gesture_counters.get("pointing", 0) >= self._gesture_hold_frames:
                if self._prev_rotation_center is not None:
                    dx = (hand.center_x - self._prev_rotation_center[0]) * self.rotation_sensitivity
                    dy = (hand.center_y - self._prev_rotation_center[1]) * self.rotation_sensitivity
                    if self.on_rotate:
                        self.on_rotate(dx, -dy)  # Y is inverted in screen coords
                self._prev_rotation_center = (hand.center_x, hand.center_y)
        else:
            self._gesture_counters["pointing"] = 0
            self._prev_rotation_center = None

    def _process_two_hands(self, hand1: HandState, hand2: HandState):
        """Two hand gestures: zoom (pinch) or pan (open palms)."""
        # Average pinch distance for zoom
        avg_pinch = (hand1.pinch_distance + hand2.pinch_distance) / 2

        both_open = hand1.is_open_palm and hand2.is_open_palm
        both_pinching = hand1.pinch_distance < 0.08 and hand2.pinch_distance < 0.08

        if both_pinching:
            self._increment_counter("pinch")
            if self._gesture_counters.get("pinch", 0) >= self._gesture_hold_frames:
                if self._prev_pinch_distance is not None:
                    zoom_delta = (self._prev_pinch_distance - avg_pinch) * self.zoom_sensitivity
                    if self.on_zoom:
                        self.on_zoom(zoom_delta)
                self._prev_pinch_distance = avg_pinch
        else:
            self._gesture_counters["pinch"] = 0
            self._prev_pinch_distance = None

        if both_open:
            self._increment_counter("pan")
            # Pan based on midpoint between hands
            mid_x = (hand1.center_x + hand2.center_x) / 2
            mid_y = (hand1.center_y + hand2.center_y) / 2
            if self._gesture_counters.get("pan", 0) >= self._gesture_hold_frames:
                if self._prev_pan_center is not None:
                    dx = (mid_x - self._prev_pan_center[0]) * self.pan_sensitivity
                    dy = (mid_y - self._prev_pan_center[1]) * self.pan_sensitivity
                    if self.on_pan:
                        self.on_pan(dx, -dy)  # Y inverted
            self._prev_pan_center = (mid_x, mid_y)
        else:
            self._gesture_counters["pan"] = 0
            self._prev_pan_center = None

    def _increment_counter(self, gesture: str):
        self._gesture_counters[gesture] = self._gesture_counters.get(gesture, 0) + 1

    def _reset_gesture_state(self):
        self._prev_rotation_center = None
        self._prev_pinch_distance = None
        self._prev_pan_center = None
        self._gesture_counters.clear()

    def status(self) -> dict:
        return {
            "enabled": self._enabled,
            "camera_index": self.camera_index,
            "backend": "mediapipe" if self.use_mediapipe else "unavailable",
            "available": bool(self.use_mediapipe and GESTURE_3D_AVAILABLE),
            "callbacks": {
                "rotate": self.on_rotate is not None,
                "zoom": self.on_zoom is not None,
                "pan": self.on_pan is not None,
                "reset": self.on_reset is not None,
            }
        }


# Convenience function for tool integration
_GLOBAL_CONTROLLER: Optional[Gesture3DController] = None

# Module-level availability flag
GESTURE_3D_AVAILABLE = _MP and _CV2 and _NP


def get_controller(camera_index: int = 0, use_mediapipe: bool = True) -> Gesture3DController:
    global _GLOBAL_CONTROLLER
    if _GLOBAL_CONTROLLER is None:
        _GLOBAL_CONTROLLER = Gesture3DController(camera_index, use_mediapipe)
    return _GLOBAL_CONTROLLER