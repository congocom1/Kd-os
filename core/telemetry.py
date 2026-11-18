"""Real-time process and system telemetry for KD.

This module collects system-wide metrics (CPU, RAM, disk, network, GPU, process
list) using psutil and nvidia-smi. It returns a JSON-serializable snapshot with
timestamps and a status flag for each group. The dashboard serves this via a
GET endpoint and streams it over a lightweight WebSocket (SSE fallback is out of
scope for this PR but the same data structure can be used there).

It is intentionally pure-Python with optional subprocess calls, so it can be run
in a CI environment without a GPU.
"""

from __future__ import annotations

import subprocess
import threading
from datetime import datetime, timezone
from typing import Any

import psutil

_PROCESS = psutil.Process()
_PROCESS_LOCK = threading.Lock()
_PROCESS_SAMPLED = False

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _probeGpu() -> dict[str, Any]:
    """Return live GPU telemetry using nvidia-smi.

    Falls back to a 'unavailable' entry when the binary is missing or the call
    fails (the app must keep running in that situation).
    """
    gpu: dict[str, Any] = {
        "status": "ok",
        "device_count": 0,
        "utilization_gpu": None,
        "memory_used_mb": None,
        "memory_total_mb": None,
        "temperature_gpu_c": None,
        "last_refresh": "",
    }
    try:
        cmd = [
            "nvidia-smi",
            "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
            "--format=csv,noheader,nounits",
        ]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=2, check=False)
        if out.returncode != 0:
            gpu["status"] = "nvidia_smi_failed"
            return gpu

        lines = [ln.strip() for ln in out.stdout.strip().splitlines() if ln.strip()]
        if not lines:
            gpu["status"] = "no_data"
            return gpu

        # Support one or multiple GPUs; counter is concatenated, but for the
        # mono-GPU host we only need the first line.
        parts = lines[0].split(",")
        if len(parts) >= 4:
            gpu["utilization_gpu"] = int(parts[0])
            # nvidia-smi already reports memory in MiB.
            gpu["memory_used_mb"] = int(parts[1])
            gpu["memory_total_mb"] = int(parts[2])
            gpu["temperature_gpu_c"] = int(parts[3])
        else:
            gpu["status"] = "invalid_data"
            return gpu
        gpu["device_count"] = len(lines)
        gpu["last_refresh"] = _now_iso()
        return gpu
    except Exception as exc:  # pragma: no cover - defensive
        gpu["status"] = "error"
        gpu["error"] = type(exc).__name__
        return gpu


def _probeDisks() -> list[dict[str, Any]]:
    """Return a small list of root + each mounted filesystem's usage."""
    out: list[dict[str, Any]] = []
    for part in psutil.disk_partitions(all=True):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except Exception:
            continue
        out.append({
            "device": part.device,
            "mountpoint": part.mountpoint,
            "fstype": part.fstype,
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "percent": round(usage.percent, 1),
        })
    return out


def _probeNetwork() -> dict[str, Any]:
    """Return aggregate network I/O for the host."""
    io = psutil.net_io_counters(pernic=False)
    return {
        "status": "ok" if io is not None else "unavailable",
        **{name: getattr(io, name, None) for name in
           ("bytes_sent", "bytes_recv", "packets_sent", "packets_recv")},
        "last_refresh": _now_iso(),
    }


def _probeDiskTemp() -> list[dict[str, Any]]:
    """Return temperatures where psutil exposes them (Linux sysfs)."""
    temps: list[dict[str, Any]] = []
    probe = getattr(psutil, "sensors_temperatures", None)
    if probe is None:
        return temps
    try:
        readings = probe(fahrenheit=False)
    except (OSError, NotImplementedError):
        return temps
    for sensor, entry in readings.items():
        for item in entry:
            # item is a namedtuple: recent, current, critical
            temps.append({
                "sensor": sensor,
                "current_c": item.current,
                "high_critical_c": item.critical,
            })
    return temps


def get_telemetry() -> dict[str, Any]:
    """Return a single real-time snapshot of host + KD process state."""
    global _PROCESS_SAMPLED
    proc = _PROCESS
    with _PROCESS_LOCK, proc.oneshot():
        cpu = proc.cpu_percent()
        process_cpu = cpu if _PROCESS_SAMPLED else None
        _PROCESS_SAMPLED = True
        proc_info = {
            "pid": proc.pid,
            "name": proc.name(),
            "cpu_percent": process_cpu,
            "memory_info": proc.memory_info()._asdict(),
            "num_threads": proc.num_threads(),
        }

    sys_cpu = psutil.cpu_percent(interval=0.1)
    sys_mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    net = _probeNetwork()
    gpu = _probeGpu()
    disks = _probeDisks()
    disks_temp = _probeDiskTemp()

    return {
        "schema_version": "1.0",
        "timestamp": _now_iso(),
        "status": "ok" if gpu["status"] == net["status"] == "ok" else "partial",
        "process": proc_info,
        "system": {
            "cpu_percent": sys_cpu,
            "cpu_count": psutil.cpu_count(),
            "memory_total_mb": round(sys_mem.total / (1024 * 1024), 1),
            "memory_available_mb": round(sys_mem.available / (1024 * 1024), 1),
            "memory_percent": sys_mem.percent,
            "swap_total_mb": round(swap.total / (1024 * 1024), 1),
            "swap_used_mb": round(swap.used / (1024 * 1024), 1),
            "swap_percent": swap.percent,
            "disks": disks,
            "disk_temp_c": disks_temp,
            "network": net,
        },
        "gpu": gpu,
    }
