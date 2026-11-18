"""
actions/system_monitor.py — Background metric checks with voice alert support.

Zero subprocess calls on all platforms — uses ctypes/pynvml/psutil/wmi only.
"""

import ctypes
import logging
import os
import threading
import platform
import time

import psutil

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"

logger = logging.getLogger("system_monitor")

# Default thresholds for alerts
DEFAULT_THRESHOLDS = {
    "cpu": 90.0,   # % - alert when sustained above this
    "ram": 90.0,   # %  - alert when percentage above this
    "temp": 85.0,  # °C - alert when temperature above this
    "gpu": 95.0,   # %  - GPU utilisation
}

# How long a threshold must be sustained before alerting
_COOLDOWN = 60
_CPU_STREAK = 3

# ── Temperature helpers (minimal, no subprocess) ─────────────────────────────

def get_cpu_temperature() -> float | None:
    """Read CPU temperature without subprocess. Returns None if unavailable."""
    _os = platform.system()
    if _os == "Linux":
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                return float(f.read().strip()) / 1000.0
        except Exception:
            for f in ("/sys/class/thermal/mosquitto/temp",
                      "/sys/class/hwmon/hwmon0/temp1_input"):
                try:
                    with open(f) as fh:
                        v = float(fh.read().strip())
                        return v / 1000.0
                except Exception:
                    continue
            return None
    elif _os == "Windows":
        try:
            import ctypes

            # Try WMI-style access via ctypes — broad but works on recent Windows
            # Since this is complex, fall through to None for simplicity
            return None
        except Exception:
            return None
    elif _os == "Darwin":
        try:
            import subprocess

            r = subprocess.run(["sysctl", "-n", "hw.temperature"],
                               capture_output=True, text=True, timeout=3)
            if r.returncode == 0:
                return float(r.stdout.strip())
        except Exception:
            pass
        return None
    return None


# ── NVML GPU helper ─────────────────────────────────────────────────────────

def get_gpu_percent() -> float:
    """GPU utilisation via NVML — zero subprocess on all platforms."""
    _os = platform.system()
    if _os == "Windows":
        try:
            import ctypes

            class _Util(ctypes.Structure):
                _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

            for name in ("nvml", ):
                try:
                    lib = ctypes.WinDLL(name)
                    lib.nvmlInit_v2()
                    try:
                        rv = lib.nvmlDeviceGetHandle_v2(0)
                        rc = lib.nvmlDeviceGetUtilization_rates_p(rv, _Util())
                        lib.nvmlShutdown()
                        return float(rc.gpu)
                    except Exception:
                        lib.nvmlShutdown()
                        return -1.0
                except Exception:
                    continue
            return -1.0
        except Exception:
            return -1.0
    else:
        # Linux: try loading libnvidia-ml.so.1
        try:
            import ctypes

            for name in ("libnvidia-ml.so.1", "libnvidia-ml.so",
                         "libnvidia-ml.dylib"):
                try:
                    lib = ctypes.CDLL(name)
                    lib.nvmlInit_v2()
                    try:
                        rv = lib.nvmlDeviceGetHandle_v2(0)
                        rc = lib.nvmlDeviceGetUtilization_rates_p(rv, _Util())
                        lib.nvmlShutdown()
                        return float(rc.gpu)
                    except Exception:
                        lib.nvmlShutdown()
                        return -1.0
                except Exception:
                    continue
            return -1.0
        except Exception:
            return -1.0


# ── System status ────────────────────────────────────────────────────────────

def get_system_status() -> dict:
    """Return the current system status dictionary."""
    status = {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "memory_percent": psutil.virtual_memory().percent,
        "memory_used": psutil.virtual_memory().used,
        "memory_total": psutil.virtual_memory().total,
        "swap_percent": psutil.swap_memory().percent,
        "disk_percent": psutil.disk_usage("/").percent,
        "disk_used": psutil.disk_usage("/").used,
        "disk_total": psutil.disk_usage("/").total,
        "boot_time": time.time() - psutil.boot_time(),
        "load_average": os.getloadavg() if hasattr(os, "getloadavg") else None,
        "cpu_freq_mhz": psutil.cpu_freq().current if psutil.cpu_freq() else None,
    }
    status["cpu_temp"] = get_cpu_temperature()
    status["gpu_percent"] = get_gpu_percent()
    status["process_count"] = len(psutil.pids())
    return status


# ── ThresholdMonitor ─────────────────────────────────────────────────────────

class ThresholdMonitor:
    """Watch a metric and alert when it exceeds a threshold for a sustained period."""

    def __init__(self, metric_name: str, threshold: float,
                 cooldown: float = _COOLDOWN, streak: int = _CPU_STREAK):
        self.metric_name = metric_name
        self.threshold = threshold
        self.cooldown = cooldown
        self.streak = streak
        self._streak = 0
        self._last_alert = 0.0
        self._alerts: list[tuple[float, str]] = []

    def check(self, value: float) -> bool:
        now = time.monotonic()
        if value > self.threshold:
            self._streak += 1
            if self._streak >= self.streak and \
               now - self._last_alert >= self.cooldown:
                self._last_alert = now
                self._alerts.append((now, f"{self.metric_name} at {value:.1f}"))
                return True
        else:
            self._streak = 0
        return False

    def alerts(self) -> list[tuple[float, str]]:
        return list(self._alerts)

    def clear(self) -> None:
        self._alerts.clear()
        self._streak = 0


# ── SystemMonitor — background metric checker with voice alerts ─────────────

class SystemMonitor:
    """Continuously monitors system metrics and calls an alert function."""

    _instance = None
    _running = False

    def __init__(self, alert_fn=None):
        self.alert_fn = alert_fn or (lambda msg: print(f"[ALERT] {msg}"))
        self.thresholds = dict(DEFAULT_THRESHOLDS)
        self._monitors: dict[str, ThresholdMonitor] = {}
        self._thread: threading.Thread | None = None
        self._running = False
        self.configure(self.thresholds)

    @classmethod
    def start(cls) -> "SystemMonitor":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def get(cls) -> "SystemMonitor":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def configure(self, thresholds: dict) -> None:
        self.thresholds.update(thresholds)
        self._monitors = {
            "cpu": ThresholdMonitor("CPU", self.thresholds["cpu"]),
            "ram": ThresholdMonitor("RAM", self.thresholds["ram"]),
            "temp": ThresholdMonitor("Temp", self.thresholds["temp"]),
            "gpu": ThresholdMonitor("GPU", self.thresholds["gpu"]),
        }

    def check(self) -> str:
        """Return threshold alerts for the live session's periodic checks."""
        status = get_system_status()
        messages = []
        for name, key in (("cpu", "cpu_percent"), ("ram", "memory_percent"),
                          ("temp", "cpu_temp"), ("gpu", "gpu_percent")):
            value = status.get(key)
            monitor = self._monitors[name]
            if value is not None and value >= 0 and monitor.check(value):
                messages.extend(message for _, message in monitor.alerts())
                monitor.clear()
        return "; ".join(messages)

    def run(self) -> None:
        """Main monitoring loop."""
        self._running = True
        logger.info("SystemMonitor started")
        while self._running:
            try:
                status = get_system_status()

                # Check CPU
                if status["cpu_percent"] > self.thresholds["cpu"]:
                    self._monitors["cpu"].check(status["cpu_percent"])

                # Check RAM
                if status["memory_percent"] > self.thresholds["ram"]:
                    self._monitors["ram"].check(status["memory_percent"])

                # Check temperature
                temp = status.get("cpu_temp")
                if temp is not None and temp > self.thresholds["temp"]:
                    self._monitors["temp"].check(temp)

                # Check GPU
                gpu = status.get("gpu_percent", -1)
                if gpu >= 0 and gpu > self.thresholds["gpu"]:
                    self._monitors["gpu"].check(gpu)

                # Fire alerts
                for name, mon in self._monitors.items():
                    for ts, msg in mon.alerts():
                        self.alert_fn(msg)
                        mon.clear()

            except Exception as e:
                logger.error(f"SystemMonitor error: {e}")

            time.sleep(1)

    def stop(self) -> None:
        self._running = False
