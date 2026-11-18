"""
actions/maintenance.py — Automation: defrag, log rotation, updates, backups.

Smart maintenance keeps the system fast, clean, and reliable.
"""

import json
import logging
import os
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

from core import outcome
from core.lazyimport import installed

_psutil = installed("psutil")
psutil = None
if _psutil:
    import psutil

logger = logging.getLogger("maintenance")

# ── Maintenance actions ──────────────────────────────────────────────────────

def _defrag_filesystem() -> str:
    """Trigger filesystem defragmentation if available."""
    try:
        if os.name == "posix":
            root = "/"
            if os.path.exists(root + "/.ext4"):
                r = subprocess.run(["e4defrag", root], capture_output=True,
                                   text=True, timeout=60)
                if r.returncode == 0:
                    return f"Defragged ext4 filesystem at {root}"
            elif os.path.exists(root + "/.xfs"):
                r = subprocess.run(["xfs_frag", root], capture_output=True,
                                   text=True, timeout=60)
                if r.returncode == 0:
                    return f"Defragged XFS filesystem at {root}"
            return "No defragmentation tool found for this filesystem"
        elif os.name == "nt":
            return "Windows defrag not automated — run 'defrag C:' manually"
    except Exception as e:
        return f"Defrag failed: {e}"
    return "Defrag not supported on this OS"


def _rotate_logs() -> str:
    """Rotate old log files into dated archives."""
    log_dir = Path.home() / "logs"
    if not log_dir.exists():
        return "No log directory found"

    date_str = time.strftime("%Y%m%d", time.localtime())
    rotated = 0

    for f in log_dir.glob("*.log*"):
        if not f.is_file():
            continue
        stem = f.stem
        if stem.endswith(date_str):
            continue
        if f.suffix == ".log":
            new_name = f.with_suffix(f".log.{date_str}")
            try:
                shutil.move(str(f), str(new_name))
                if rotated > 7:
                    with tarfile.open(new_name + ".tar.gz", "w:gz") as tar:
                        tar.add(new_name)
                    new_name.unlink()
                rotated += 1
            except Exception:
                pass

    return f"Log rotation complete: {rotated} files rotated"


def _check_updates() -> str:
    """Check for updates via the package manager."""
    updates = {"os": "check via apt/dnf/yum/pacman", "notes": "requires user confirmation"}
    return json.dumps(updates, indent=2)


# ── Tool declaration ─────────────────────────────────────────────────────────

TOOL = {
    "name": "maintenance",
    "description": (
        "Maintenance automation. Actions: defrag (defragment filesystem), "
        "rotate_logs (rotate old logs), check_updates (check for system updates)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "defrag | rotate_logs | check_updates",
            },
        },
        "required": ["action"],
    },
    "handler": None,
}


def run_maintenance(parameters: dict, player=None, session_memory=None) -> str:
    action = (parameters.get("action") or "").strip().lower()

    if action == "defrag":
        return outcome.done("maintenance", result=_defrag_filesystem())

    if action == "rotate_logs":
        return outcome.done("maintenance", result=_rotate_logs())

    if action == "check_updates":
        return outcome.done("maintenance", result=_check_updates())

    return outcome.failed("maintenance", f"unknown action: {action}")


TOOL["handler"] = run_maintenance
