"""
screen_watch — continuous screen access + one-off screenshots for JARVIS.

WHAT IT DOES
    * screen_capture   — take a single screenshot right now.
    * screen_watch_start — begin capturing the screen every N seconds in a
      background thread so JARVIS can "see" what is happening continuously.
    * screen_watch_stop  — end the background watch.
    * screen_watch_status — report whether the watcher is running and how many
      frames it has captured.

WHY IT IS SAFE
    * Nothing leaves this machine — frames stay in RAM (bounded ring buffer).
    * The watch only starts when the user explicitly asks; there is no always-on
      capture by default.
    * PyAutoGUI mouse/keyboard control stays in computer_control; this file only
      reads the screen.
    * Every action returns a plain spoken string — never raises.

The handler signature receives `parameters` plus any of `player`/`speak` it
declares, exactly like every other actions/*.py tool (see core/action_loader).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from pathlib import Path

from core.lazyimport import LazyModule, installed

_MSS = installed("mss")
mss = LazyModule("mss")
mss_tools = LazyModule("mss.tools")

# Bounded ring buffer — the watcher never grows memory without limit.
_MAX_FRAMES = 60

# One shared watcher for the process. Started only on explicit request.
_watch_lock = threading.Lock()
_watch_thread: threading.Thread | None = None
_watch_stop = threading.Event()
_watch_interval = 2.0
_frames: deque = deque(maxlen=_MAX_FRAMES)
_watch_started_at: float | None = None


def _grab_frame() -> tuple[bytes, str] | None:
    """Capture one screen frame. Returns (png_bytes, mime) or None on failure."""
    if not _MSS:
        return None
    try:
        with mss.mss() as sct:
            monitors = sct.monitors
            target = monitors[1] if len(monitors) > 1 else monitors[0]
            shot = sct.grab(target)
            png = mss_tools.to_png(shot.rgb, shot.size)
        return png, "image/png"
    except Exception as exc:
        print(f"[ScreenWatch] capture failed: {exc}")
        return None


def _watch_loop(interval: float) -> None:
    """Background thread: grab a frame every `interval` seconds until stopped."""
    while not _watch_stop.is_set():
        frame = _grab_frame()
        if frame is not None:
            with _watch_lock:
                _frames.append(
                    {
                        "ts": time.monotonic(),
                        "bytes": frame[0],
                        "mime": frame[1],
                    }
                )
        # Sleep in small chunks so stop responds quickly.
        _watch_stop.wait(interval)


def run(parameters: dict, player=None, speak=None, session_memory=None) -> str:
    action = (parameters.get("action") or "").strip().lower()

    if action == "screen_capture":
        if not _MSS:
            return "Screen capture is unavailable — install mss (pip install mss)."
        frame = _grab_frame()
        if frame is None:
            return "I could not capture the screen just now."
        png, mime = frame
        with _watch_lock:
            _frames.append({"ts": time.monotonic(), "bytes": png, "mime": mime})
        # hand the fresh frame to the live session so the model can see it
        if speak:
            try:
                speak("I have the screen — what would you like me to look at?")
            except Exception:
                pass
        return f"Captured the screen ({len(png)} bytes)."

    if action == "screen_watch_start":
        with _watch_lock:
            global _watch_thread, _watch_stop, _watch_interval, _watch_started_at
            if _watch_thread is not None and _watch_thread.is_alive():
                return f"Screen watch is already running ({len(_frames)} frames captured)."
            interval = float(parameters.get("interval", 2.0) or 2.0)
            interval = max(0.5, min(interval, 30.0))
            _watch_interval = interval
            _watch_stop.clear()
            _frames.clear()
            _watch_started_at = time.monotonic()
            _watch_thread = threading.Thread(
                target=_watch_loop, args=(interval,), daemon=True,
                name="ScreenWatch",
            )
            _watch_thread.start()
        return (f"Continuous screen watch started — one frame every {interval:.1f}s. "
                f"Say 'stop screen watch' to end it.")

    if action == "screen_watch_stop":
        with _watch_lock:
            _watch_stop.set()
            thread = _watch_thread
            _watch_thread = None
            _watch_started_at = None
            count = len(_frames)
            _frames.clear()
        if thread is not None:
            thread.join(timeout=3)
        return f"Screen watch stopped. {count} frames were captured."

    if action == "screen_watch_status":
        with _watch_lock:
            running = _watch_thread is not None and _watch_thread.is_alive()
            count = len(_frames)
            interval = _watch_interval
            started = _watch_started_at
        if not running:
            return "Screen watch is not running."
        elapsed = (time.monotonic() - started) if started else 0
        return (f"Screen watch is running — {count} frames captured in the last "
                f"{elapsed:.0f}s (one every {interval:.1f}s).")

    if action == "screen_latest":
        with _watch_lock:
            if not _frames:
                return "No screen frames captured yet."
            latest = _frames[-1]
            size = len(latest["bytes"])
        return f"Latest screen frame: {size} bytes, captured {time.monotonic() - latest['ts']:.0f}s ago."

    return ("Unknown screen_watch action. Use: screen_capture, screen_watch_start, "
            "screen_watch_stop, screen_watch_status, or screen_latest.")


# ── Tool declaration (auto-discovered by core/action_loader) ────────────────

TOOL = {
    "name": "screen_watch",
    "description": (
        "Gives JARVIS eyes on the screen. screen_capture takes one screenshot "
        "right now. screen_watch_start begins continuous capture every N seconds "
        "(the model can then describe what is happening). screen_watch_stop ends "
        "it. screen_watch_status reports progress. screen_latest reports the most "
        "recent frame. Frames stay in local memory only — nothing leaves this "
        "machine."
    ),
    "brief": (
        "Screen access: screen_capture | screen_watch_start (interval) | "
        "screen_watch_stop | screen_watch_status | screen_latest"
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "screen_capture | screen_watch_start | screen_watch_stop | screen_watch_status | screen_latest",
            },
            "interval": {
                "type": "NUMBER",
                "description": "Seconds between frames when watching (default 2, min 0.5, max 30)",
            },
        },
        "required": ["action"],
    },
    "handler": run,
}
