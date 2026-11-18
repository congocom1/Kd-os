"""
System Info skill — reports CPU, memory, and disk usage.

Uses psutil (already a project dependency). Auto-discovered by core/plugin_loader.
"""

import logging
logger = logging.getLogger(__name__)

import platform

import psutil

PLUGIN = {
    "name": "system_info",
    "description": (
        "Reports the computer's current system status: CPU usage, memory (RAM) "
        "usage, disk usage, and OS details. Use when the user asks how the "
        "machine is performing or what resources are available."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
        "required": [],
    },
}

def _test_info(values: dict) -> tuple[bool, str]:
    """Probe that system info can be read."""
    try:
        interval = float(values.get("cpu_interval", 0.5) or 0.5)
        p = psutil.cpu_percent(interval=min(interval, 2.0))
        m = psutil.virtual_memory()
        return True, f"OK — CPU {p}%, RAM {m.percent}%"
    except Exception as e:
        return False, f"Error: {e}"


# ── Plugin settings (shown in ⚙ → PLUGINS → system_info) ──────────────────
PLUGIN_SETTINGS = {
    "namespace": "system_info",
    "title": "System Info",
    "fields": [
        {
            "key": "cpu_interval",
            "label": "CPU sample interval (seconds)",
            "type": "number",
            "default": 0.5,
            "placeholder": "0.5",
        },
    ],
    "action": {
        "label": "REFRESH",
        "run": _test_info,
    },
}


def _fmt_bytes(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Get system information.

    Returns system info including CPU, memory, OS, and other hardware details.

    Parameters:
        parameters: Dict with optional "detail_level" key.

    Returns:
        String with system information.
    """
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        boot = psutil.boot_time()
    except Exception as e:
        logger.error("System info error", exc_info=True)
        return "I had trouble reading system status."

    from datetime import datetime

    boot_str = datetime.fromtimestamp(boot).strftime("%Y-%m-%d %H:%M")

    lines = [
        f"OS: {platform.system()} {platform.release()} ({platform.machine()})",
        f"CPU load: {cpu}%",
        f"Memory: {_fmt_bytes(mem.used)} / {_fmt_bytes(mem.total)} ({mem.percent}% used)",
        f"Disk (/): {_fmt_bytes(disk.used)} / {_fmt_bytes(disk.total)} ({disk.percent}% used)",
        f"Up since: {boot_str}",
    ]
    answer = "System status, sir:\n" + "\n".join(lines)
    if player:
        try:
            player.write_log(f"JARVIS: {answer}")
        except Exception:
            pass
    return answer
