"""
core/os.py — JARVIS OS kernel: process table, memory management, task
scheduler, virtual filesystem, device abstraction, and string dict.
"""

from __future__ import annotations

import atexit
import os as host_os
import sys
import time
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from core.paths import get_base_dir as _get_base_dir


@dataclass
class Process:
    pid: int
    name: str
    cmdline: list[str]
    started: float
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    ppid: int = 0
    is_running: bool = True

    def __post_init__(self) -> None:
        self.started = time.monotonic()


class ProcessTable:
    """Lightweight process table. Monitored by a background thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[int, Process] = {}
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [self._entry_to_dict(p) for p in self._entries.values()]

    def _entry_to_dict(self, p: Process) -> dict:
        return {
            "pid": p.pid,
            "name": p.name,
            "cmdline": " ".join(p.cmdline),
            "started": p.started,
            "cpu_percent": p.cpu_percent,
            "memory_percent": p.memory_percent,
            "ppid": p.ppid,
        }

    def add(self, pid: int, name: str, cmdline: list[str],
            ppid: int = 0) -> None:
        with self._lock:
            self._entries[pid] = Process(
                pid=pid, name=name, cmdline=cmdline,
                started=time.monotonic(), ppid=ppid,
            )

    def remove(self, pid: int) -> None:
        with self._lock:
            self._entries.pop(pid, None)

    def update(self, pid: int, cpu: float, mem: float) -> None:
        with self._lock:
            if pid in self._entries:
                entry = self._entries[pid]
                entry.cpu_percent = cpu
                entry.memory_percent = mem

    def iterate(self, callback: Callable[[Process], None]) -> None:
        with self._lock:
            for p in self._entries.values():
                callback(p)


class OS:
    """The operating system kernel. One global instance, `os`.

    Responsibilities (L0):
      - Process table (PID namespace)
      - Virtual filesystem (mount points, file ops)
      - Device abstraction layer
      - String dict / global config
      - Task scheduler placeholder
      - Boot/shutdown hooks
    """

    _instance: Optional["OS"] = None

    def __new__(cls) -> "OS":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        self.process_table = ProcessTable()
        self._string_dict: dict[str, str] = {}
        self._mounted: dict[str, Path] = {}
        self._devices: dict[str, object] = {}
        self._shutdown_hooks: list[Callable[[], None]] = []
        self._reboot_hooks: list[Callable[[], None]] = []
        self._booted = False
        atexit.register(self.shutdown)

    def boot(self) -> None:
        """Kernel bootstrap. Called once at startup."""
        if self._booted:
            return
        self._booted = True
        self._start_monitor_thread()

    def get_base_dir(self) -> Path:
        return _get_base_dir()

    def _register_shutdown_hooks(self) -> None:
        # Auto-register a clean shutdown for the main process
        def _on_exit() -> None:
            self.shutdown()
        atexit.register(_on_exit)

    def _start_monitor_thread(self) -> None:
        import psutil

        def _monitor() -> None:
            while self._booted:
                try:
                    for proc in psutil.process_iter(["pid", "name", "cmdline",
                                                       "ppid", "cpu_percent",
                                                       "memory_percent"]):
                        try:
                            self.process_table.add(
                                proc.info["pid"], proc.info["name"] or "",
                                proc.info["cmdline"] or [], proc.info["ppid"] or 0,
                            )
                            self.process_table.update(
                                proc.info["pid"],
                                proc.info["cpu_percent"] or 0,
                                proc.info["memory_percent"] or 0,
                            )
                        except (psutil.NoSuchProcess, KeyError):
                            pass
                except Exception:
                    pass
                time.sleep(1.0)

        thread = threading.Thread(target=_monitor, daemon=True, name="os-monitor")
        thread.start()

    # ── Virtual filesystem ────────────────────────────────────────────────

    def mount(self, mountpoint: str, location: Path) -> str:
        if host_os.path.isabs(mountpoint):
            raise ValueError(f"mountpoint must be relative: {mountpoint}")
        self._mounted[mountpoint] = location
        return f"mounted {location} at {mountpoint}"

    def umount(self, mountpoint: str) -> str:
        self._mounted.pop(mountpoint, None)
        return f"unmounted {mountpoint}"

    def resolve(self, path: str) -> Path:
        """Resolve a path against mounted volumes."""
        if host_os.path.isabs(path):
            return Path(path)
        for name, location in self._mounted.items():
            if path.startswith(name + "/"):
                return location / path[len(name) + 1:]
        return Path(path)

    def list_mounts(self) -> list[dict]:
        return [{"mountpoint": k, "location": str(v)} for k, v in self._mounted.items()]

    # ── Device abstraction ────────────────────────────────────────────────

    def add_device(self, name: str, device: object) -> str:
        self._devices[name] = device
        return f"device '{name}' registered"

    def get_device(self, name: str) -> Optional[object]:
        return self._devices.get(name)

    def list_devices(self) -> list[str]:
        return list(self._devices.keys())

    # ── Shell / string dict ───────────────────────────────────────────────

    def set(self, key: str, value: str) -> str:
        self._string_dict[key] = str(value)
        return f"{key} = {value}"

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return self._string_dict.get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self._string_dict

    def __getitem__(self, key: str) -> str:
        return self._string_dict[key]

    # ── Task scheduler placeholder ────────────────────────────────────────

    def schedule(self, target: Callable, args: tuple = (), kwargs: dict = {}) -> int:
        """Schedule a task. Returns a task ID."""
        # Placeholder — a real scheduler would use asyncio or a job queue.
        thread = threading.Thread(
            target=target, args=args, kwargs=kwargs, daemon=True
        )
        thread.start()
        return id(thread)

    # ── Boot / shutdown ───────────────────────────────────────────────────

    def shutdown(self) -> None:
        if not self._booted:
            return
        self._booted = False
        for hook in self._shutdown_hooks:
            try:
                hook()
            except Exception:
                pass
        print("[OS] shutdown complete")

    def register_shutdown(self, hook: Callable[[], None]) -> None:
        self._shutdown_hooks.append(hook)

    def register_reboot(self, hook: Callable[[], None]) -> None:
        self._reboot_hooks.append(hook)

    def reboot(self) -> None:
        for hook in self._reboot_hooks:
            try:
                hook()
            except Exception:
                pass
        print("[OS] reboot requested")
        host_os.execvpe(sys.executable, [sys.executable] + sys.argv, host_os.environ)


# Global singleton
os = OS()
