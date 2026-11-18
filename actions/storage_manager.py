"""
actions/storage_manager.py — Disk, storage, and filesystems.

Provides: status (overall storage), mounts (mounted volumes),
monitor (threshold warnings), clean (free space).
"""

import os
import shutil
from pathlib import Path

from core import outcome
from core.lazyimport import installed

_psutil = installed("psutil")
psutil = None
if _psutil:
    import psutil

_STORAGE_POINTS = ["/", "/home", "/tmp", "/var"]


# ── Action implementations ───────────────────────────────────────────────────

def _storage_status():
    """Return overall storage status across mounted volumes."""
    if psutil:
        disks = []
        for part in psutil.disk_partitions(all=True):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks.append({
                    "device": part.device,
                    "mount": part.mountpoint,
                    "fstype": part.fstype,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": usage.percent,
                })
            except Exception:
                pass
        # Use the root partition for summary
        root = next((d for d in disks if d["mount"] == "/"), disks[0] if disks else None)
        return {"disks": disks, "root": root}
    else:
        return {"disks": [], "error": "psutil not available"}


def _storage_partitions():
    """List all mounted filesystems."""
    if psutil:
        return _storage_status()["disks"]
    return []


def _storage_monitor():
    """Check for low-disk conditions and return any issues."""
    if not psutil:
        return []

    issues = []
    for part in psutil.disk_partitions(all=True):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            pct = usage.percent
            if pct > 90:
                issues.append({
                    "mount": part.mountpoint,
                    "percent": pct,
                    "level": "critical",
                    "message": f"Disk {part.mountpoint} is {pct:.1f}% full",
                })
            elif pct > 75:
                issues.append({
                    "mount": part.mountpoint,
                    "percent": pct,
                    "level": "warning",
                    "message": f"Disk {part.mountpoint} is at {pct:.1f}%",
                })
        except Exception:
            continue
    return issues


def _free_space(path: str = "/"):
    """Return human-readable free space for a path."""
    try:
        usage = shutil.disk_usage(path)
        return f"{usage.free / (1024**3):.2f} GB free on {path}"
    except Exception:
        return f"Could not determine free space for {path}"


# ── Tool declaration ─────────────────────────────────────────────────────────

TOOL = {
    "name": "storage_manager",
    "description": (
        "Storage management. Actions: status (overall storage across volumes), "
        "partitions (list mounted filesystems), monitor (check for low-disk "
        "conditions), free (available space for a path)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "status | partitions | monitor | free",
            },
            "path": {"type": "STRING", "description": "Path for free action"},
        },
        "required": ["action"],
    },
    "handler": None,  # override via run function
}


def run_storage_manager(parameters: dict, player=None, session_memory=None) -> str:
    """Handler for the storage_manager tool."""
    action = (parameters.get("action") or "").strip().lower()

    if action == "status":
        return outcome.done("storage_manager", **_storage_status())

    if action == "partitions":
        return outcome.done("storage_manager", **_storage_partitions())

    if action == "monitor":
        issues = _storage_monitor()
        if issues:
            return outcome.done("storage_manager", issues=issues)
        return outcome.done("storage_manager", message="no low-disk conditions")

    if action == "free":
        path = parameters.get("path", "/")
        return outcome.done("storage_manager", **_free_space(path))

    return outcome.failed("storage_manager", f"unknown action: {action}")


TOOL["handler"] = run_storage_manager
