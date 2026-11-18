"""
core/window_manager.py — Dynamic Window Management (KD Upgrade).

Provides cross-platform window management:
  • Window enumeration, focus, geometry
  • Layout engine (tiling, cascading, grids)
  • Window rules (per-app positioning, sizing)
  • Integration with awareness engine for context
  • Zero-regression: gated by DYNAMIC_WINDOWS flag

Platform backends: Windows (win32gui), Linux (X11/Wayland via ewmh), macOS (Quartz)
"""

from __future__ import annotations

import logging
import platform
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from core.feature_flags import is_enabled
from core.awareness_engine import get_awareness_engine, EventType, WindowPayload

logger = logging.getLogger("jarvis.window_manager")


# ── Data Types ────────────────────────────────────────────────────────────────

class WindowState(Enum):
    NORMAL = "normal"
    MINIMIZED = "minimized"
    MAXIMIZED = "maximized"
    FULLSCREEN = "fullscreen"


@dataclass
class WindowInfo:
    """Complete window information."""
    window_id: str
    title: str
    app_name: str
    pid: int
    bounds: dict  # x, y, width, height
    state: WindowState = WindowState.NORMAL
    focused: bool = False
    visible: bool = True
    monitor: int = 0
    z_order: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "window_id": self.window_id,
            "title": self.title,
            "app_name": self.app_name,
            "pid": self.pid,
            "bounds": self.bounds,
            "state": self.state.value,
            "focused": self.focused,
            "visible": self.visible,
            "monitor": self.monitor,
            "z_order": self.z_order,
            "timestamp": self.timestamp,
        }


@dataclass
class MonitorInfo:
    """Monitor/display information."""
    monitor_id: int
    name: str
    bounds: dict  # x, y, width, height
    work_area: dict  # x, y, width, height (excluding taskbar/dock)
    is_primary: bool
    scale: float = 1.0


@dataclass
class LayoutRule:
    """Rule for automatic window layout."""
    name: str
    app_pattern: str  # Regex or exact match for app name/title
    action: str  # "tile", "maximize", "position", "monitor"
    params: dict = field(default_factory=dict)  # Action-specific parameters
    priority: int = 0
    enabled: bool = True


# ── Layout Engine ─────────────────────────────────────────────────────────────

class LayoutEngine:
    """Calculates window layouts for tiling, grids, etc."""

    @staticmethod
    def tile_windows(windows: list[WindowInfo], work_area: dict,
                     direction: str = "horizontal", gap: int = 4) -> dict[str, dict]:
        """
        Calculate tiled layout for windows.

        Returns dict of window_id -> bounds.
        """
        if not windows:
            return {}

        n = len(windows)
        x, y, w, h = work_area["x"], work_area["y"], work_area["width"], work_area["height"]

        if direction == "horizontal":
            # Side by side
            tile_w = (w - gap * (n - 1)) // n
            result = {}
            for i, win in enumerate(windows):
                result[win.window_id] = {
                    "x": x + i * (tile_w + gap),
                    "y": y,
                    "width": tile_w,
                    "height": h,
                }
            return result

        elif direction == "vertical":
            # Stacked
            tile_h = (h - gap * (n - 1)) // n
            result = {}
            for i, win in enumerate(windows):
                result[win.window_id] = {
                    "x": x,
                    "y": y + i * (tile_h + gap),
                    "width": w,
                    "height": tile_h,
                }
            return result

        elif direction == "grid":
            # Grid layout
            cols = int(n ** 0.5)
            if cols == 0:
                cols = 1
            rows = (n + cols - 1) // cols
            tile_w = (w - gap * (cols - 1)) // cols
            tile_h = (h - gap * (rows - 1)) // rows
            result = {}
            for i, win in enumerate(windows):
                row = i // cols
                col = i % cols
                result[win.window_id] = {
                    "x": x + col * (tile_w + gap),
                    "y": y + row * (tile_h + gap),
                    "width": tile_w,
                    "height": tile_h,
                }
            return result

        elif direction == "main_stack":
            # Main window large, others stacked on side
            if n == 1:
                return {windows[0].window_id: {"x": x, "y": y, "width": w, "height": h}}
            main_w = int(w * 0.65)
            side_w = w - main_w - gap
            tile_h = (h - gap * (n - 2)) // (n - 1) if n > 2 else h
            result = {
                windows[0].window_id: {"x": x, "y": y, "width": main_w, "height": h},
            }
            for i, win in enumerate(windows[1:]):
                result[win.window_id] = {
                    "x": x + main_w + gap,
                    "y": y + i * (tile_h + gap),
                    "width": side_w,
                    "height": tile_h,
                }
            return result

        return {}

    @staticmethod
    def cascade_windows(windows: list[WindowInfo], work_area: dict,
                        offset: int = 30) -> dict[str, dict]:
        """Calculate cascaded layout."""
        result = {}
        x, y, w, h = work_area["x"], work_area["y"], work_area["width"], work_area["height"]
        for i, win in enumerate(windows):
            result[win.window_id] = {
                "x": x + i * offset,
                "y": y + i * offset,
                "width": min(w - i * offset, w // 2 + 200),
                "height": min(h - i * offset, h // 2 + 150),
            }
        return result


# ── Platform Backend Interface ────────────────────────────────────────────────

class WindowBackend:
    """Abstract base for platform-specific window operations."""

    def enumerate_windows(self) -> list[WindowInfo]:
        raise NotImplementedError

    def get_active_window(self) -> WindowInfo | None:
        raise NotImplementedError

    def get_window(self, window_id: str) -> WindowInfo | None:
        raise NotImplementedError

    def set_window_bounds(self, window_id: str, bounds: dict) -> bool:
        raise NotImplementedError

    def set_window_state(self, window_id: str, state: WindowState) -> bool:
        raise NotImplementedError

    def focus_window(self, window_id: str) -> bool:
        raise NotImplementedError

    def close_window(self, window_id: str) -> bool:
        raise NotImplementedError

    def get_monitors(self) -> list[MonitorInfo]:
        raise NotImplementedError

    def get_window_at_point(self, x: int, y: int) -> WindowInfo | None:
        raise NotImplementedError


# ── Windows Backend (win32gui) ────────────────────────────────────────────────

class WindowsBackend(WindowBackend):
    """Windows implementation using win32gui/win32con."""

    def __init__(self):
        self._hwnd_map: dict[str, int] = {}  # window_id -> hwnd
        self._load_win32()

    def _load_win32(self) -> None:
        try:
            import win32gui
            import win32con
            import win32process
            self.win32gui = win32gui
            self.win32con = win32con
            self.win32process = win32process
            self._available = True
        except ImportError:
            self._available = False
            logger.warning("win32gui not available - Windows backend disabled")

    def _hwnd_to_id(self, hwnd: int) -> str:
        return f"win_{hwnd}"

    def _get_window_info(self, hwnd: int) -> WindowInfo | None:
        if not self.win32gui.IsWindowVisible(hwnd):
            return None
        if not self.win32gui.GetWindowText(hwnd):
            return None

        try:
            _, pid = self.win32process.GetWindowThreadProcessId(hwnd)
            rect = self.win32gui.GetWindowRect(hwnd)
            title = self.win32gui.GetWindowText(hwnd)
            # Get class name for app identification
            class_name = self.win32gui.GetClassName(hwnd)

            # Determine window state
            placement = self.win32gui.GetWindowPlacement(hwnd)
            state = WindowState.NORMAL
            if placement[1] == self.win32con.SW_SHOWMINIMIZED:
                state = WindowState.MINIMIZED
            elif placement[1] == self.win32con.SW_SHOWMAXIMIZED:
                state = WindowState.MAXIMIZED

            focused = hwnd == self.win32gui.GetForegroundWindow()

            window_id = self._hwnd_to_id(hwnd)
            self._hwnd_map[window_id] = hwnd

            return WindowInfo(
                window_id=window_id,
                title=title,
                app_name=class_name,
                pid=pid,
                bounds={
                    "x": rect[0],
                    "y": rect[1],
                    "width": rect[2] - rect[0],
                    "height": rect[3] - rect[1],
                },
                state=state,
                focused=focused,
                visible=True,
            )
        except Exception:
            return None

    def enumerate_windows(self) -> list[WindowInfo]:
        if not self._available:
            return []
        windows = []

        def enum_callback(hwnd, _):
            info = self._get_window_info(hwnd)
            if info:
                windows.append(info)
            return True

        self.win32gui.EnumWindows(enum_callback, None)
        return windows

    def get_active_window(self) -> WindowInfo | None:
        if not self._available:
            return None
        hwnd = self.win32gui.GetForegroundWindow()
        return self._get_window_info(hwnd)

    def get_window(self, window_id: str) -> WindowInfo | None:
        if not self._available:
            return None
        hwnd = self._hwnd_map.get(window_id)
        if hwnd:
            return self._get_window_info(hwnd)
        return None

    def set_window_bounds(self, window_id: str, bounds: dict) -> bool:
        if not self._available:
            return False
        hwnd = self._hwnd_map.get(window_id)
        if not hwnd:
            return False
        try:
            self.win32gui.SetWindowPos(
                hwnd, 0,
                bounds["x"], bounds["y"],
                bounds["width"], bounds["height"],
                self.win32con.SWP_NOZORDER | self.win32con.SWP_NOACTIVATE
            )
            return True
        except Exception:
            return False

    def set_window_state(self, window_id: str, state: WindowState) -> bool:
        if not self._available:
            return False
        hwnd = self._hwnd_map.get(window_id)
        if not hwnd:
            return False
        try:
            if state == WindowState.MINIMIZED:
                self.win32gui.ShowWindow(hwnd, self.win32con.SW_MINIMIZE)
            elif state == WindowState.MAXIMIZED:
                self.win32gui.ShowWindow(hwnd, self.win32con.SW_MAXIMIZE)
            elif state == WindowState.NORMAL:
                self.win32gui.ShowWindow(hwnd, self.win32con.SW_RESTORE)
            return True
        except Exception:
            return False

    def focus_window(self, window_id: str) -> bool:
        if not self._available:
            return False
        hwnd = self._hwnd_map.get(window_id)
        if not hwnd:
            return False
        try:
            self.win32gui.SetForegroundWindow(hwnd)
            return True
        except Exception:
            return False

    def close_window(self, window_id: str) -> bool:
        if not self._available:
            return False
        hwnd = self._hwnd_map.get(window_id)
        if not hwnd:
            return False
        try:
            self.win32gui.PostMessage(hwnd, self.win32con.WM_CLOSE, 0, 0)
            return True
        except Exception:
            return False

    def get_monitors(self) -> list[MonitorInfo]:
        if not self._available:
            return []
        monitors = []
        try:
            import win32api
            for i, monitor in enumerate(win32api.EnumDisplayMonitors()):
                handle, _, rect = monitor
                info = win32api.GetMonitorInfo(handle)
                work = info["Work"]
                mon_rect = info["Monitor"]
                monitors.append(MonitorInfo(
                    monitor_id=i,
                    name=f"Monitor {i}",
                    bounds={"x": mon_rect[0], "y": mon_rect[1],
                            "width": mon_rect[2] - mon_rect[0],
                            "height": mon_rect[3] - mon_rect[1]},
                    work_area={"x": work[0], "y": work[1],
                               "width": work[2] - work[0],
                               "height": work[3] - work[1]},
                    is_primary=(i == 0),
                ))
        except Exception:
            pass
        return monitors

    def get_window_at_point(self, x: int, y: int) -> WindowInfo | None:
        if not self._available:
            return None
        hwnd = self.win32gui.WindowFromPoint((x, y))
        return self._get_window_info(hwnd) if hwnd else None


# ── Linux Backend (X11 via python-xlib / ewmh) ────────────────────────────────

class LinuxBackend(WindowBackend):
    """Linux implementation using X11/EWMH."""

    def __init__(self):
        self._available = False
        self._load_x11()

    def _load_x11(self) -> None:
        try:
            from Xlib import display, X
            from Xlib.xobject.drawable import Window as XWindow
            import ewmh
            self.display = display.Display()
            self.root = self.display.screen().root
            self.ewmh = ewmh.EWMH(self.display)
            self.X = X
            self._available = True
        except ImportError:
            logger.debug("Xlib/ewmh not available - Linux backend disabled")

    def _window_to_id(self, window) -> str:
        return f"x11_{window.id}"

    def enumerate_windows(self) -> list[WindowInfo]:
        if not self._available:
            return []
        windows = []
        try:
            # Get all top-level windows
            tree = self.root.query_tree()
            for window in tree.children:
                info = self._get_window_info(window)
                if info:
                    windows.append(info)
        except Exception as e:
            logger.debug(f"Window enumeration failed: {e}")
        return windows

    def _get_window_info(self, window) -> WindowInfo | None:
        try:
            # Get window title
            title = window.get_wm_name() or ""
            if not title:
                return None

            # Get PID
            pid = 0
            try:
                pid_prop = window.get_full_property(self.display.intern_atom("_NET_WM_PID"), 0)
                if pid_prop:
                    pid = pid_prop.value[0]
            except Exception:
                pass

            # Get geometry
            geom = window.get_geometry()
            bounds = {
                "x": geom.x,
                "y": geom.y,
                "width": geom.width,
                "height": geom.height,
            }

            # Get state
            state = WindowState.NORMAL
            try:
                wm_state = window.get_full_property(self.display.intern_atom("_NET_WM_STATE"), 0)
                if wm_state:
                    atoms = [self.display.get_atom_name(a) for a in wm_state.value]
                    if "_NET_WM_STATE_MAXIMIZED_VERT" in atoms and "_NET_WM_STATE_MAXIMIZED_HORZ" in atoms:
                        state = WindowState.MAXIMIZED
                    elif "_NET_WM_STATE_FULLSCREEN" in atoms:
                        state = WindowState.FULLSCREEN
            except Exception:
                pass

            # Get class for app name
            app_name = ""
            try:
                cls = window.get_wm_class()
                if cls:
                    app_name = cls[0]
            except Exception:
                pass

            window_id = self._window_to_id(window)
            return WindowInfo(
                window_id=window_id,
                title=title,
                app_name=app_name,
                pid=pid,
                bounds=bounds,
                state=state,
                visible=True,
            )
        except Exception:
            return None

    def get_active_window(self) -> WindowInfo | None:
        if not self._available:
            return None
        try:
            active = self.ewmh.getActiveWindow()
            if active:
                return self._get_window_info(active)
        except Exception:
            pass
        return None

    def get_window(self, window_id: str) -> WindowInfo | None:
        if not self._available:
            return None
        try:
            # Parse window ID
            win_id = int(window_id.split("_")[1])
            window = self.display.create_resource_object('window', win_id)
            return self._get_window_info(window)
        except Exception:
            return None

    def set_window_bounds(self, window_id: str, bounds: dict) -> bool:
        if not self._available:
            return False
        try:
            win_id = int(window_id.split("_")[1])
            window = self.display.create_resource_object('window', win_id)
            window.configure(
                x=bounds["x"], y=bounds["y"],
                width=bounds["width"], height=bounds["height"]
            )
            self.display.sync()
            return True
        except Exception:
            return False

    def set_window_state(self, window_id: str, state: WindowState) -> bool:
        if not self._available:
            return False
        try:
            win_id = int(window_id.split("_")[1])
            window = self.display.create_resource_object('window', win_id)
            atoms = []
            if state == WindowState.MAXIMIZED:
                atoms = [
                    self.display.intern_atom("_NET_WM_STATE_MAXIMIZED_VERT"),
                    self.display.intern_atom("_NET_WM_STATE_MAXIMIZED_HORZ"),
                ]
            elif state == WindowState.FULLSCREEN:
                atoms = [self.display.intern_atom("_NET_WM_STATE_FULLSCREEN")]
            elif state == WindowState.MINIMIZED:
                # Iconify
                window.iconify()
                self.display.sync()
                return True

            if atoms:
                self.ewmh.setWmState(window, atoms, [])
                self.display.sync()
            return True
        except Exception:
            return False

    def focus_window(self, window_id: str) -> bool:
        if not self._available:
            return False
        try:
            win_id = int(window_id.split("_")[1])
            window = self.display.create_resource_object('window', win_id)
            self.ewmh.setActiveWindow(window)
            self.display.sync()
            return True
        except Exception:
            return False

    def close_window(self, window_id: str) -> bool:
        if not self._available:
            return False
        try:
            win_id = int(window_id.split("_")[1])
            window = self.display.create_resource_object('window', win_id)
            window.destroy()
            self.display.sync()
            return True
        except Exception:
            return False

    def get_monitors(self) -> list[MonitorInfo]:
        # Simplified: return primary monitor info
        try:
            screen = self.display.screen()
            return [MonitorInfo(
                monitor_id=0,
                name="Primary",
                bounds={"x": 0, "y": 0, "width": screen.width_in_pixels, "height": screen.height_in_pixels},
                work_area={"x": 0, "y": 0, "width": screen.width_in_pixels, "height": screen.height_in_pixels},
                is_primary=True,
            )]
        except Exception:
            return []

    def get_window_at_point(self, x: int, y: int) -> WindowInfo | None:
        if not self._available:
            return None
        try:
            window = self.root.child_at(x, y)
            while window and window != self.root:
                info = self._get_window_info(window)
                if info:
                    return info
                window = window.query_tree().parent
        except Exception:
            pass
        return None


# ── Linux Backend (xdotool / wmctrl) ───────────────────────────────────────────

class XdotoolBackend(WindowBackend):
    """Linux/X11 implementation using only xdotool + wmctrl.

    The Xlib/ewmh backend above needs two pip packages that are not installed
    on every machine; these two CLIs are already present on ordinary desktops
    and speak to the same X server, so window control still works without
    adding a dependency. On Wayland both CLIs talk to the XWayland server, so
    X11 windows are managed and native Wayland windows are not — which is why
    every method degrades to "unavailable" instead of guessing.
    """

    def __init__(self):
        self._available = False
        self._xdotool = shutil.which("xdotool")
        self._wmctrl = shutil.which("wmctrl")
        self._available = bool(self._xdotool or self._wmctrl)
        if not self._available:
            logger.debug("Neither xdotool nor wmctrl found - Linux backend disabled")

    def _run(self, args: list[str], timeout: float = 5.0) -> str:
        import subprocess
        try:
            proc = subprocess.run(args, capture_output=True, text=True,
                                  timeout=timeout)
            return proc.stdout or ""
        except Exception:
            return ""

    def _run_wmctrl(self, args: list[str]) -> str:
        if not self._wmctrl:
            return ""
        return self._run([self._wmctrl, *args])

    def _run_xdotool(self, args: list[str]) -> str:
        if not self._xdotool:
            return ""
        return self._run([self._xdotool, *args])

    def enumerate_windows(self) -> list[WindowInfo]:
        if not self._available:
            return []
        windows: list[WindowInfo] = []
        out = self._run_wmctrl(["-l", "-p", "-x"])
        for line in out.splitlines():
            # wmctrl -l -p -x prints:
            #   <id> <desktop> <pid> <WM_CLASS> (<host>)<class>  <title>
            # The desktop column may be empty and the WM_CLASS may contain
            # spaces, so the line is parsed from both ends rather than by
            # splitting on whitespace.
            match = re.match(
                r"^(0x[0-9a-fA-F]+)\s+(?:(-?\d+)\s+)?(\d+)\s+(.*)$", line)
            if not match:
                continue
            wid, pid_str, rest = match.group(1), match.group(3), match.group(4)
            try:
                pid = int(pid_str)
            except ValueError:
                pid = 0

            # Split "<class> (<host>)<class>" away from the title.
            host_match = re.search(r"\s\([^)]*\)\S*\s+(.*)$", rest)
            if host_match:
                cls = rest[: host_match.start()].strip()
                title = host_match.group(1).strip()
            else:
                cls, title = "", rest.strip()

            try:
                bounds = self._geometry(self._decimal_id(wid))
            except Exception:
                bounds = {"x": 0, "y": 0, "width": 0, "height": 0}
            windows.append(WindowInfo(
                window_id=f"x11_{wid}",
                title=title,
                app_name=cls,
                pid=pid,
                bounds=bounds,
                focused=self._decimal_id(self._active_id()) == self._decimal_id(wid),
            ))
        return windows

    @staticmethod
    def _decimal_id(window_id: str) -> str:
        """wmctrl prints hexadecimal ids; xdotool wants decimal."""
        wid = str(window_id or "").strip()
        if wid.lower().startswith("0x"):
            try:
                return str(int(wid, 16))
            except ValueError:
                return wid
        return wid

    def _active_id(self) -> str:
        return self._run_xdotool(["getactivewindow"]).strip()

    def _geometry(self, wid: str) -> dict:
        out = self._run_xdotool(["getwindowgeometry", "--shell", wid])
        vals = {}
        for line in out.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                vals[k.strip().lower()] = v.strip()
        return {
            "x": int(vals.get("x", 0)),
            "y": int(vals.get("y", 0)),
            "width": int(vals.get("width", 0)),
            "height": int(vals.get("height", 0)),
        }

    def _numeric_id(self, window_id: str) -> str:
        """The bare window id from "x11_<id>" — decimal, for xdotool."""
        return self._decimal_id(window_id.split("_", 1)[-1])

    def get_active_window(self) -> WindowInfo | None:
        if not self._available:
            return None
        wid = self._active_id()
        if not wid:
            return None
        for win in self.enumerate_windows():
            if win.window_id == f"x11_{wid}":
                return win
        return None

    def get_window(self, window_id: str) -> WindowInfo | None:
        for win in self.enumerate_windows():
            if win.window_id == window_id:
                return win
        return None

    def set_window_bounds(self, window_id: str, bounds: dict) -> bool:
        if not self._available or not self._xdotool:
            return False
        wid = self._numeric_id(window_id)
        w = int(bounds.get("width", 0))
        h = int(bounds.get("height", 0))
        if w <= 0 or h <= 0:
            return False
        self._run_xdotool([
            "windowmove", wid, str(int(bounds.get("x", 0))),
            str(int(bounds.get("y", 0))),
            "windowsize", wid, str(w), str(h),
        ])
        return True

    def set_window_state(self, window_id: str, state: WindowState) -> bool:
        if not self._available or not self._xdotool:
            return False
        wid = self._numeric_id(window_id)
        if state == WindowState.MINIMIZED:
            self._run_xdotool(["windowminimize", wid])
            return True
        if state == WindowState.MAXIMIZED:
            self._run_xdotool(["windowmaximize", wid])
            return True
        if state == WindowState.NORMAL:
            self._run_xdotool(["windowrestore", wid])
            return True
        return False

    def focus_window(self, window_id: str) -> bool:
        if not self._available or not self._xdotool:
            return False
        self._run_xdotool(["windowactivate", "--sync",
                           self._numeric_id(window_id)])
        return True

    def close_window(self, window_id: str) -> bool:
        if not self._available or not self._xdotool:
            return False
        self._run_xdotool(["windowclose", self._numeric_id(window_id)])
        return True

    def get_monitors(self) -> list[MonitorInfo]:
        if not self._available:
            return []
        out = self._run(["xrandr", "--query"])
        monitors: list[MonitorInfo] = []
        idx = 0
        for line in out.splitlines():
            if " connected" not in line:
                continue
            name = line.split()[0]
            geometry = ""
            for token in line.split():
                if "x" in token and "+" in token:
                    geometry = token
                    break
            if not geometry:
                continue
            size_part, _, offset = geometry.partition("+")
            try:
                w, h = (int(v) for v in size_part.lower().split("x"))
                ox, _, oy = offset.partition("+")
                x, y = int(ox), int(oy.split("+")[0])
            except Exception:
                continue
            monitors.append(MonitorInfo(
                monitor_id=idx,
                name=name,
                bounds={"x": x, "y": y, "width": w, "height": h},
                work_area={"x": x, "y": y, "width": w, "height": h},
                is_primary=(idx == 0),
            ))
            idx += 1
        return monitors

    def get_window_at_point(self, x: int, y: int) -> WindowInfo | None:
        # The CLIs cannot hit-test reliably; report the focused window rather
        # than guessing a position-based answer.
        return self.get_active_window()

class MacOSBackend(WindowBackend):
    """macOS implementation using Quartz/CoreGraphics."""

    def __init__(self):
        self._available = False
        self._load_quartz()

    def _load_quartz(self) -> None:
        try:
            import Quartz
            self.Quartz = Quartz
            self._available = True
        except ImportError:
            logger.debug("Quartz not available - macOS backend disabled")

    def enumerate_windows(self) -> list[WindowInfo]:
        if not self._available:
            return []
        windows = []
        try:
            window_list = self.Quartz.CGWindowListCopyWindowInfo(
                self.Quartz.kCGWindowListOptionOnScreenOnly,
                self.Quartz.kCGNullWindowID
            )
            for w in window_list:
                if w.get(self.Quartz.kCGWindowLayer, 0) != 0:
                    continue  # Skip non-standard layers
                title = w.get(self.Quartz.kCGWindowName, "")
                if not title:
                    continue
                bounds_dict = w.get(self.Quartz.kCGWindowBounds, {})
                bounds = {
                    "x": int(bounds_dict.get("X", 0)),
                    "y": int(bounds_dict.get("Y", 0)),
                    "width": int(bounds_dict.get("Width", 0)),
                    "height": int(bounds_dict.get("Height", 0)),
                }
                pid = w.get(self.Quartz.kCGWindowOwnerPID, 0)
                app_name = w.get(self.Quartz.kCGWindowOwnerName, "")
                window_id = f"quartz_{w.get(self.Quartz.kCGWindowNumber, 0)}"
                windows.append(WindowInfo(
                    window_id=window_id,
                    title=title,
                    app_name=app_name,
                    pid=pid,
                    bounds=bounds,
                    visible=True,
                ))
        except Exception as e:
            logger.debug(f"macOS window enumeration failed: {e}")
        return windows

    def get_active_window(self) -> WindowInfo | None:
        # macOS doesn't have a simple "active window" concept like X11/Windows
        # Return frontmost window
        windows = self.enumerate_windows()
        return windows[0] if windows else None

    def get_window(self, window_id: str) -> WindowInfo | None:
        for win in self.enumerate_windows():
            if win.window_id == window_id:
                return win
        return None

    # macOS window manipulation requires accessibility permissions
    # These are stubs - real implementation needs AXUIElement
    def set_window_bounds(self, window_id: str, bounds: dict) -> bool:
        logger.warning("Window bounds manipulation not implemented for macOS (requires Accessibility API)")
        return False

    def set_window_state(self, window_id: str, state: WindowState) -> bool:
        return False

    def focus_window(self, window_id: str) -> bool:
        return False

    def close_window(self, window_id: str) -> bool:
        return False

    def get_monitors(self) -> list[MonitorInfo]:
        try:
            main_display = self.Quartz.CGMainDisplayID()
            bounds = self.Quartz.CGDisplayBounds(main_display)
            return [MonitorInfo(
                monitor_id=0,
                name="Main Display",
                bounds={"x": int(bounds.origin.x), "y": int(bounds.origin.y),
                        "width": int(bounds.size.width), "height": int(bounds.size.height)},
                work_area={"x": 0, "y": 0, "width": int(bounds.size.width), "height": int(bounds.size.height)},
                is_primary=True,
            )]
        except Exception:
            return []

    def get_window_at_point(self, x: int, y: int) -> WindowInfo | None:
        # Would need hit-testing via Quartz
        return None


# ── Window Manager ────────────────────────────────────────────────────────────

class WindowManager:
    """
    High-level window manager with layout engine and rules.

    Features:
    - Cross-platform window enumeration and control
    - Automatic layout application (tiling, grids, cascading)
    - Per-app window rules
    - Integration with awareness engine for context
    """

    def __init__(self):
        self._backend: WindowBackend | None = None
        self._rules: list[LayoutRule] = []
        self._lock = threading.RLock()
        self._awareness = None
        self._event_token: int | None = None
        self._monitor_thread: threading.Thread | None = None
        self._running = False
        self._init_backend()

    def _init_backend(self) -> None:
        """Initialize platform-specific backend."""
        system = platform.system()
        if system == "Windows":
            self._backend = WindowsBackend()
        elif system == "Linux":
            # Prefer the Xlib/ewmh backend when its packages are installed,
            # but fall back to xdotool/wmctrl so the feature is not dead on a
            # machine that never installed them.
            backend = LinuxBackend()
            if not getattr(backend, "_available", False):
                backend = XdotoolBackend()
            self._backend = backend
        elif system == "Darwin":
            self._backend = MacOSBackend()
        else:
            logger.warning(f"No window backend for platform: {system}")

        if self._backend and not getattr(self._backend, '_available', False):
            logger.warning(f"Backend initialized but not available on {system}")
            self._backend = None

    def start(self) -> None:
        """Start the window manager (monitoring + awareness integration)."""
        if not is_enabled("DYNAMIC_WINDOWS"):
            logger.info("Window manager not started: DYNAMIC_WINDOWS flag is off")
            return
        if not self._backend:
            logger.warning("Window manager has no available backend")
            return
        if self._running:
            return

        # Connect to awareness engine
        if is_enabled("REALTIME_AWARENESS"):
            try:
                self._awareness = get_awareness_engine()
                if not self._awareness._started:
                    self._awareness.start()
            except Exception as e:
                logger.warning(f"Could not connect to awareness engine: {e}")

        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="WindowMonitor"
        )
        self._monitor_thread.start()
        logger.info("Window manager started")

    def stop(self) -> None:
        """Stop the window manager."""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2.0)
        logger.info("Window manager stopped")

    def _monitor_loop(self) -> None:
        """Background loop to track window changes and publish events."""
        last_focused: str | None = None
        last_windows: dict[str, WindowInfo] = {}

        while self._running:
            try:
                # Get current windows
                windows = self.enumerate_windows()
                current_windows = {w.window_id: w for w in windows}

                # Detect focus changes
                active = self.get_active_window()
                if active and active.window_id != last_focused:
                    last_focused = active.window_id
                    self._publish_focus_event(active)

                # Detect new/closed windows
                for win_id, win in current_windows.items():
                    if win_id not in last_windows:
                        self._publish_window_event(EventType.WINDOW_CREATED, win)
                for win_id in last_windows:
                    if win_id not in current_windows:
                        # Window closed
                        pass  # Could publish WINDOW_CLOSED

                last_windows = current_windows

                # Apply layout rules for new windows
                self._apply_rules(windows)

            except Exception as e:
                logger.debug(f"Window monitor error: {e}")

            time.sleep(1.0)  # Poll every second

    def _publish_focus_event(self, window: WindowInfo) -> None:
        """Publish window focus event to awareness engine."""
        if self._awareness:
            payload = WindowPayload(
                window_id=window.window_id,
                title=window.title,
                app_name=window.app_name,
                bounds=window.bounds,
                focused=True,
            )
            self._awareness._awareness._event_bus.publish(
                EventType.WINDOW_FOCUS,
                payload.__dict__
            )

    def _publish_window_event(self, event_type: str, window: WindowInfo) -> None:
        """Publish window event to awareness engine."""
        if self._awareness:
            payload = WindowPayload(
                window_id=window.window_id,
                title=window.title,
                app_name=window.app_name,
                bounds=window.bounds,
                focused=window.focused,
            )
            self._awareness._awareness._event_bus.publish(event_type, payload.__dict__)

    def _apply_rules(self, windows: list[WindowInfo]) -> None:
        """Apply layout rules to matching windows."""
        for rule in self._rules:
            if not rule.enabled:
                continue
            import re
            for window in windows:
                if re.search(rule.app_pattern, window.app_name, re.IGNORECASE) or \
                   re.search(rule.app_pattern, window.title, re.IGNORECASE):
                    self._apply_rule_to_window(rule, window)

    def _apply_rule_to_window(self, rule: LayoutRule, window: WindowInfo) -> None:
        """Apply a single rule to a window."""
        if rule.action == "maximize":
            self.set_window_state(window.window_id, WindowState.MAXIMIZED)
        elif rule.action == "position":
            bounds = rule.params.get("bounds")
            if bounds:
                self.set_window_bounds(window.window_id, bounds)
        elif rule.action == "monitor":
            # Move to specific monitor
            monitor = rule.params.get("monitor", 0)
            monitors = self.get_monitors()
            if 0 <= monitor < len(monitors):
                work = monitors[monitor].work_area
                self.set_window_bounds(window.window_id, work)

    # ── Public API ────────────────────────────────────────────────────────────

    def enumerate_windows(self) -> list[WindowInfo]:
        """Get all visible windows."""
        if not self._backend:
            return []
        return self._backend.enumerate_windows()

    def get_active_window(self) -> WindowInfo | None:
        """Get the currently focused window."""
        if not self._backend:
            return None
        return self._backend.get_active_window()

    def get_window(self, window_id: str) -> WindowInfo | None:
        """Get window by ID."""
        if not self._backend:
            return None
        return self._backend.get_window(window_id)

    def set_window_bounds(self, window_id: str, bounds: dict) -> bool:
        """Set window position and size."""
        if not self._backend:
            return False
        return self._backend.set_window_bounds(window_id, bounds)

    def set_window_state(self, window_id: str, state: WindowState) -> bool:
        """Set window state (minimize, maximize, restore)."""
        if not self._backend:
            return False
        return self._backend.set_window_state(window_id, state)

    def focus_window(self, window_id: str) -> bool:
        """Bring window to front and focus it."""
        if not self._backend:
            return False
        return self._backend.focus_window(window_id)

    def close_window(self, window_id: str) -> bool:
        """Close a window gracefully."""
        if not self._backend:
            return False
        return self._backend.close_window(window_id)

    def get_monitors(self) -> list[MonitorInfo]:
        """Get all monitors."""
        if not self._backend:
            return []
        return self._backend.get_monitors()

    def get_window_at_point(self, x: int, y: int) -> WindowInfo | None:
        """Get window at screen coordinates."""
        if not self._backend:
            return None
        return self._backend.get_window_at_point(x, y)

    # ── Layout Operations ────────────────────────────────────────────────────

    def tile_windows(self, window_ids: list[str] | None = None,
                     direction: str = "horizontal", gap: int = 4,
                     monitor: int = 0) -> dict[str, dict]:
        """
        Tile windows on a monitor.

        Args:
            window_ids: Specific windows to tile (None = all on monitor)
            direction: "horizontal", "vertical", "grid", "main_stack"
            gap: Pixel gap between windows
            monitor: Monitor index

        Returns:
            Dict of window_id -> applied bounds
        """
        windows = self.enumerate_windows()
        monitors = self.get_monitors()

        if monitor >= len(monitors):
            monitor = 0
        work_area = monitors[monitor].work_area if monitors else {"x": 0, "y": 0, "width": 1920, "height": 1080}

        if window_ids:
            target_windows = [w for w in windows if w.window_id in window_ids]
        else:
            # All windows on the monitor
            target_windows = [
                w for w in windows
                if work_area["x"] <= w.bounds["x"] < work_area["x"] + work_area["width"]
            ]

        layout = LayoutEngine.tile_windows(target_windows, work_area, direction, gap)
        applied = {}
        for win_id, bounds in layout.items():
            if self.set_window_bounds(win_id, bounds):
                applied[win_id] = bounds
        return applied

    def cascade_windows(self, window_ids: list[str] | None = None,
                        monitor: int = 0, offset: int = 30) -> dict[str, dict]:
        """Cascade windows."""
        windows = self.enumerate_windows()
        monitors = self.get_monitors()
        if monitor >= len(monitors):
            monitor = 0
        work_area = monitors[monitor].work_area if monitors else {"x": 0, "y": 0, "width": 1920, "height": 1080}

        if window_ids:
            target_windows = [w for w in windows if w.window_id in window_ids]
        else:
            target_windows = [
                w for w in windows
                if work_area["x"] <= w.bounds["x"] < work_area["x"] + work_area["width"]
            ]

        layout = LayoutEngine.cascade_windows(target_windows, work_area, offset)
        applied = {}
        for win_id, bounds in layout.items():
            if self.set_window_bounds(win_id, bounds):
                applied[win_id] = bounds
        return applied

    # ── Rule Management ──────────────────────────────────────────────────────

    def add_rule(self, rule: LayoutRule) -> None:
        """Add a layout rule."""
        with self._lock:
            self._rules.append(rule)
            self._rules.sort(key=lambda r: -r.priority)

    def remove_rule(self, name: str) -> bool:
        """Remove a rule by name."""
        with self._lock:
            for i, rule in enumerate(self._rules):
                if rule.name == name:
                    self._rules.pop(i)
                    return True
            return False

    def list_rules(self) -> list[LayoutRule]:
        """Get all layout rules."""
        with self._lock:
            return list(self._rules)

    def load_rules_from_config(self, config_path: Path) -> None:
        """Load rules from JSON config file."""
        import json
        if not config_path.exists():
            return
        try:
            data = json.loads(config_path.read_text())
            for rule_data in data.get("rules", []):
                rule = LayoutRule(**rule_data)
                self.add_rule(rule)
        except Exception as e:
            logger.warning(f"Failed to load window rules: {e}")

    def save_rules_to_config(self, config_path: Path) -> None:
        """Save rules to JSON config file."""
        import json
        try:
            data = {"rules": [vars(r) for r in self._rules]}
            config_path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save window rules: {e}")


# ── Singleton ────────────────────────────────────────────────────────────────

_manager: WindowManager | None = None


def get_window_manager() -> WindowManager | None:
    """Get or create the global window manager."""
    global _manager
    if not is_enabled("DYNAMIC_WINDOWS"):
        return None
    if _manager is None:
        _manager = WindowManager()
    return _manager