"""
actions/backup.py — Backup and restore system state.

Creates incremental backups of configurations, memories, and custom files.
Implements a simple system image for rapid restore.
"""

import json
import shutil
import tarfile
import time
from pathlib import Path

from core import outcome
from core.lazyimport import installed

_psutil = installed("psutil")
psutil = None
if _psutil:
    import psutil

# Directories to back up
BACKUP_SRC = [
    "config",
    "memory",
    "plugins",
    "providers",
    "dashboard",
    "core",
    "actions",
]

# Directories to exclude
BACKUP_EXCLUDE = [
    "__pycache__",
    "*.pyc",
    ".git",
    "*.log",
]


def _get_backup_name() -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    return f"backup_{ts}"


def _get_backup_dir() -> Path:
    return Path.home() / "Backups"


def _collect_files(src_dir: Path, exclude: list) -> list[Path]:
    files = []
    for p in src_dir.rglob("*"):
        if p.is_file():
            rel = p.relative_to(src_dir)
            if any(excl in str(rel) for excl in exclude):
                continue
            files.append(p)
    return files


def _create_backup() -> str:
    name = _get_backup_name()
    dest = _get_backup_dir() / name
    dest.mkdir(parents=True, exist_ok=True)

    for src_name in BACKUP_SRC:
        src = Path(src_name)
        if not src.exists():
            continue
        archive = dest / f"{src_name}.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for f in _collect_files(src, BACKUP_EXCLUDE):
                tar.add(f, arcname=f.relative_to(src))

    index = {
        "backup_name": name,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "files_backuped": [],
        "size_bytes": 0,
    }
    with open(dest / "index.json", "w") as f:
        json.dump(index, f, indent=2)

    return str(dest)


def _restore(backup_name: str) -> str:
    backup_dir = _get_backup_dir() / backup_name
    if not backup_dir.exists():
        return f"Backup '{backup_name}' not found"

    index_path = backup_dir / "index.json"
    if index_path.exists():
        with open(index_path) as f:
            json.load(f)

    for archive in backup_dir.glob("*.tar.gz"):
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(path=Path(__file__).parent.parent)

    return f"Restored from backup '{backup_name}'"


def _list_backups():
    backup_dir = _get_backup_dir()
    if not backup_dir.exists():
        return {"backups": [], "count": 0}
    backups = []
    for d in backup_dir.iterdir():
        if d.is_dir() and (d / "index.json").exists():
            id = d.name
            with open(d / "index.json") as f:
                info = json.load(f)
            backups.append({
                "name": d.name,
                "created": info.get("created", ""),
                "size": info.get("size_bytes", 0),
            })
    return {"backups": backups, "count": len(backups)}


# ── Tool declaration ─────────────────────────────────────────────────────────

TOOL = {
    "name": "backup",
    "description": (
        "Backup and restore system state. Actions: create (create a new backup), "
        "list (list available backups), restore (restore a named backup)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "create | list | restore",
            },
            "backup_name": {"type": "STRING", "description": "Name for restore"},
        },
        "required": ["action"],
    },
    "handler": None,
}


def run_backup(parameters: dict, player=None, session_memory=None) -> str:
    action = (parameters.get("action") or "").strip().lower()

    if action == "create":
        result = _create_backup()
        return outcome.done("backup", result=result)

    if action == "list":
        result = _list_backups()
        return outcome.done("backup", **result)

    if action == "restore":
        name = parameters.get("backup_name", "")
        if not name:
            return outcome.failed("backup", "no backup_name provided")
        result = _restore(name)
        return outcome.done("backup", result=result)

    return outcome.failed("backup", f"unknown action: {action}")


TOOL["handler"] = run_backup
