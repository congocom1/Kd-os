# gesture_control.py
# Camera-based hand gesture control for JARVIS.
#
# Detects hand gestures from the webcam using OpenCV (skin-color segmentation
# + convexity-defect finger counting) and maps them to system actions — volume,
# media playback, and so on. Runs as a background watcher so the assistant can
# act on gestures without a spoken command.
#
# Auto-discovered by core/action_loader via the TOOL dict below.

from __future__ import annotations

import json
import platform as _platform
import sys
import threading
import time
from pathlib import Path

from core import outcome
from core.lazyimport import LazyModule, installed

# OpenCV is imported on first USE, never at launch — see core/lazyimport.py.
_CV2 = installed("cv2")
cv2 = LazyModule("cv2")

# pyautogui drives the actual system actions (volume, media keys, ...).
_PYAUTOGUI = installed("pyautogui")
pyautogui = LazyModule("pyautogui")

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


def _get_os() -> str:
    _sys = _platform.system()
    if _sys == "Darwin":
        return "mac"
    if _sys == "Linux":
        return "linux"
    return "windows"


# ── Gesture → action map ──────────────────────────────────────────────────────
# Finger counts recognised by the detector. Each maps to one or more
# pyautogui hotkeys/presses, chosen per OS.

_DEFAULT_MAP = {
    "0": {  # fist
        "action": "mute_toggle",
        "label": "Mute / unmute",
    },
    "1": {  # index finger
        "action": "play_pause",
        "label": "Play / pause",
    },
    "2": {  # peace sign
        "action": "next_track",
        "label": "Next track",
    },
    "3": {  # three fingers
        "action": "prev_track",
        "label": "Previous track",
    },
    "4": {  # four fingers
        "action": "volume_up",
        "label": "Volume up",
    },
    "5": {  # open palm
        "action": "volume_down",
        "label": "Volume down",
    },
}


def _os_media_key(action: str) -> str:
    """Return the pyautogui key name for a media action on this OS."""
    # All platforms use the same pyautogui media key names.
    return {
        "play_pause": "playpause",
        "next_track": "nexttrack",
        "prev_track": "prevtrack",
        "volume_up": "volumeup",
        "volume_down": "volumedown",
        "mute_toggle": "volumemute",
    }.get(action, action)


# ── Background watcher ────────────────────────────────────────────────────────

class _GestureWatcher:
    """Captures camera frames on a background thread and fires mapped actions
    when a stable gesture is recognised."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._enabled = False
        self._gesture_map: dict[str, dict] = dict(_DEFAULT_MAP)
        self._cooldown = 1.5  # seconds between firings of the same gesture
        self._stable_frames = 8  # consecutive frames a gesture must hold
        self._last_fire: dict[str, float] = {}
        self._camera_index = 0
        self._current_gesture: str | None = None
        self._current_streak = 0
        self._lock = threading.Lock()
        self.log = print  # replaced by the caller with player.write_log

    # ── configuration ─────────────────────────────────────────────────

    def enable(self, enabled: bool, camera_index: int = 0) -> None:
        with self._lock:
            if enabled and not self._enabled:
                self._enabled = True
                self._camera_index = camera_index
                self._stop.clear()
                self._thread = threading.Thread(
                    target=self._loop, daemon=True, name="gesture-watcher"
                )
                self._thread.start()
                self.log("[Gesture] watcher started")
            elif not enabled and self._enabled:
                self._enabled = False
                self._stop.set()
                if self._thread is not None:
                    self._thread.join(timeout=3.0)
                self._thread = None
                self.log("[Gesture] watcher stopped")

    def set_map(self, gesture_map: dict[str, dict]) -> None:
        with self._lock:
            self._gesture_map = dict(gesture_map)

    def gesture_map(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._gesture_map)

    def set_cooldown(self, seconds: float) -> None:
        with self._lock:
            self._cooldown = max(0.3, float(seconds))

    def set_stable_frames(self, frames: int) -> None:
        with self._lock:
            self._stable_frames = max(1, int(frames))

    def status(self) -> dict:
        with self._lock:
            return {
                "enabled": self._enabled,
                "gestures": list(self._gesture_map.keys()),
                "cooldown": self._cooldown,
                "stable_frames": self._stable_frames,
                "camera_index": self._camera_index,
            }

    # ── detection loop ────────────────────────────────────────────────

    def _loop(self) -> None:
        if not _CV2 or not _NP:
            self.log("[Gesture] OpenCV or numpy unavailable — cannot run")
            with self._lock:
                self._enabled = False
            return

        backend = self._cv2_backend()
        cap = cv2.VideoCapture(self._camera_index, backend)
        if not cap.isOpened():
            self.log(f"[Gesture] camera index {self._camera_index} could not open")
            with self._lock:
                self._enabled = False
            return

        try:
            while not self._stop.is_set():
                ret, frame = cap.read()
                if not ret or frame is None:
                    time.sleep(0.05)
                    continue

                gesture = self._classify(frame)
                now = time.monotonic()

                with self._lock:
                    enabled = self._enabled
                    cooldown = self._cooldown
                    stable = self._stable_frames
                    gesture_map = dict(self._gesture_map)

                if not enabled:
                    break

                if gesture is not None:
                    if gesture == self._current_gesture:
                        self._current_streak += 1
                    else:
                        self._current_gesture = gesture
                        self._current_streak = 1

                    if self._current_streak >= stable:
                        entry = gesture_map.get(gesture)
                        if entry:
                            last = self._last_fire.get(gesture, 0.0)
                            if now - last >= cooldown:
                                self._last_fire[gesture] = now
                                action = entry.get("action", "")
                                self._fire(action)
                else:
                    self._current_gesture = None
                    self._current_streak = 0

                # Small sleep so we do not peg a CPU core watching video.
                time.sleep(0.03)
        finally:
            cap.release()
            with self._lock:
                if self._enabled:
                    self._enabled = False
                self.log("[Gesture] camera released")

    @staticmethod
    def _cv2_backend() -> int:
        os_name = _get_os()
        if os_name == "windows":
            return cv2.CAP_DSHOW
        if os_name == "mac":
            return cv2.CAP_AVFOUNDATION
        return cv2.CAP_ANY

    # ── gesture classification ────────────────────────────────────────

    def _classify(self, frame) -> str | None:
        """Return a finger-count string ('0'..'5') or None if no clear hand."""
        try:
            # Blur, convert to HSV, mask skin-like colours.
            blurred = cv2.GaussianBlur(frame, (11, 11), 0)
            hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)

            # Broad skin-tone range (works across lighting; tunable).
            lower = (0, 30, 60)
            upper = (40, 180, 255)
            mask = cv2.inRange(hsv, lower, upper)

            # Clean the mask.
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

            contours, _ = cv2.findContours(
                mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            if not contours:
                return None

            # The hand is the largest skin-coloured blob.
            hand = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(hand)
            if area < 8000:  # too small to be a hand at camera distance
                return None

            hull = cv2.convexHull(hand, returnPoints=False)
            if hull is None or len(hull) < 4:
                return "0"

            defects = cv2.convexityDefects(hand, hull)
            if defects is None:
                return "0"

            # Count deep convexity defects ≈ fingers held apart.
            fingers = 0
            for i in range(defects.shape[0]):
                s, e, f, d = defects[i, 0]
                if d > 10000:  # depth threshold, tunable
                    fingers += 1

            # Map defect count → finger count (n defects ↔ n+1 fingers for an
            # open hand; clamp to 0-5).
            count = min(fingers + 1, 5)
            return str(count)
        except Exception as e:
            # Never crash the watcher on a bad frame.
            return None

    # ── action firing ─────────────────────────────────────────────────

    def _fire(self, action: str) -> None:
        key = _os_media_key(action)
        try:
            if not _PYAUTOGUI:
                self.log(f"[Gesture] pyautogui unavailable — cannot {action}")
                return
            pyautogui.press(key)
            self.log(f"[Gesture] fired: {action} → {key}")
        except Exception as e:
            self.log(f"[Gesture] {action} failed: {e}")


# Singleton watcher shared by every tool call.
watcher = _GestureWatcher()


# ── Tool implementation ───────────────────────────────────────────────────────

def _require_cv2() -> None:
    if not _CV2:
        raise RuntimeError(
            "OpenCV (cv2) is not installed. Run: pip install opencv-python"
        )


def gesture_control(parameters: dict, player=None, session_memory=None) -> str:
    """Enable, configure, or query the gesture-control watcher.

    Parameters:
        enable:        true to start watching, false to stop
        camera_index:  which webcam to use (default 0)
        cooldown:      seconds between repeats of the same gesture (default 1.5)
        stable_frames: how many consecutive frames a gesture must hold (default 8)
        gesture_map:   JSON dict mapping finger-count strings to action entries
        status:        true to return current status without changing anything
    """
    _require_cv2()

    if player:
        watcher.log = lambda msg: (
            player.write_log(msg) if hasattr(player, "write_log") else print(msg)
        )

    if parameters.get("status", False):
        st = watcher.status()
        return (
            f"Gesture control is {'enabled' if st['enabled'] else 'disabled'}. "
            f"Camera: {st['camera_index']}. "
            f"Cooldown: {st['cooldown']}s. "
            f"Stable frames: {st['stable_frames']}. "
            f"Gestures: {', '.join(st['gestures'])}."
        )

    enable = parameters.get("enable", None)
    if enable is not None:
        camera_index = int(parameters.get("camera_index", 0))
        watcher.enable(bool(enable), camera_index=camera_index)
        labels = [v["label"] for v in watcher.gesture_map().values()]
        return (
            f"Gesture control {'enabled' if enable else 'disabled'}. "
            f"Watch the camera and hold a gesture: {', '.join(labels)}."
        )

    if "cooldown" in parameters:
        watcher.set_cooldown(float(parameters["cooldown"]))
    if "stable_frames" in parameters:
        watcher.set_stable_frames(int(parameters["stable_frames"]))
    if "gesture_map" in parameters:
        try:
            watcher.set_map(json.loads(parameters["gesture_map"]))
        except (json.JSONDecodeError, TypeError) as e:
            return outcome.failed(
                "gesture_control", f"invalid gesture_map JSON: {e}"
            )

    return outcome.done(
        "gesture_control",
        enabled=watcher.status()["enabled"],
        cooldown=watcher.status()["cooldown"],
        stable_frames=watcher.status()["stable_frames"],
    )


# ── Tool declaration (auto-discovered by core/action_loader.py) ───────────────

TOOL = {
    "name": "gesture_control",
    "description": (
        "Camera-based hand gesture control. Recognises hand gestures (finger "
        "count 0-5) from the webcam and maps each to a system action: "
        "fist=mute, one finger=play/pause, peace=next track, three fingers=previous "
        "track, four fingers=volume up, open palm=volume down. "
        "Call with enable=true to start watching, enable=false to stop, "
        "status=true to query state. Requires a webcam and good lighting."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "enable": {
                "type": "BOOLEAN",
                "description": "true to start gesture watching, false to stop",
            },
            "status": {
                "type": "BOOLEAN",
                "description": "true to return current status without changing anything",
            },
            "camera_index": {
                "type": "INTEGER",
                "description": "Which webcam to use (default: 0)",
            },
            "cooldown": {
                "type": "NUMBER",
                "description": "Seconds between repeats of the same gesture (default: 1.5)",
            },
            "stable_frames": {
                "type": "INTEGER",
                "description": "Consecutive frames a gesture must hold before firing (default: 8)",
            },
            "gesture_map": {
                "type": "STRING",
                "description": "JSON dict mapping finger-count strings ('0'..'5') to action entries",
            },
        },
        "required": [],
    },
    "handler": gesture_control,
}
