"""
actions/process_monitor.py — Process table monitoring.

Provides: list (all running processes), top (CPU/memory consumers),
kill (terminate a process by PID or name), and find (search).
"""

import os
from pathlib import Path

from core import outcome
from core.lazyimport import installed

_psutil = installed("psutil")
psutil = None
if _psutil:
    import psutil


def _snapshot() -> list[dict]:
    """Return a list of all running processes with metrics."""
    procs = []
    for p in psutil.process_iter(["pid", "name", "cmdline", "ppid",
                                   "cpu_percent", "memory_percent"]):
        try:
            info = p.info
            procs.append({
                "pid": info["pid"],
                "name": info["name"],
                "cmdline": " ".join(info["cmdline"]) if info["cmdline"] else "",
                "ppid": info["ppid"],
                "cpu_percent": info["cpu_percent"] or 0,
                "memory_percent": info["memory_percent"] or 0,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    # Sort by CPU then memory
    procs.sort(key=lambda x: x["memory_percent"], reverse=True)
    return procs


def _top(top_k: int = 10) -> str:
    """Return the top N processes by memory usage."""
    procs = _snapshot()
    top = procs[:top_k]
    lines = [f"  PID {p['pid']:>7}  {p['name']:<25}  "
             f"MEM {p['memory_percent']:>6.1f}%  CPU {p['cpu_percent']:>6.1f}%"
             for p in top]
    return "Top processes by memory:\n" + "\n".join(lines)


def _find(name: str, limit: int = 20) -> str:
    """Find processes matching a name."""
    procs = _snapshot()
    matches = [p for p in procs
               if name.lower() in p["name"].lower()
               or name.lower() in (p["cmdline"] or "").lower()]
    if not matches:
        return f"No processes matching '{name}'."
    lines = [f"  PID {p['pid']:>7}  {p['name']:<25}  MEM {p['memory_percent']:>6.1f}%"
             for p in matches[:limit]]
    return f"Processes matching '{name}':\n" + "\n".join(lines)


def _kill(pid: int | None = None, name: str | None = None) -> str:
    """Terminate a process by PID or name."""
    if pid is not None:
        try:
            p = psutil.Process(pid)
            p.terminate()
            return f"Terminated PID {pid} ({p.name()})."
        except psutil.NoSuchProcess:
            return f"Process PID {pid} not found."
        except Exception as e:
            return f"Failed to terminate PID {pid}: {e}"

    if name:
        killed = 0
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                proc = p.info
                if name.lower() in proc["name"].lower() or \
                   name.lower() in (proc["cmdline"] or "").lower():
                    p.terminate()
                    killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return f"Terminated {killed} process(es) matching '{name}'."

    return "Specify 'pid' or 'name' for kill action."


# ── Tool declaration ─────────────────────────────────────────────────────────

TOOL = {
    "name": "process_monitor",
    "description": (
        "Process monitoring. Actions: list (all processes), top (top consumers "
        "by memory), find (search by name), kill (terminate by PID or name)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "list | top | find | kill",
            },
            "pid": {"type": "INTEGER", "description": "Process ID for kill"},
            "name": {"type": "STRING", "description": "Process name for find/kill"},
            "limit": {
                "type": "INTEGER",
                "description": "Number of results for list/top/find",
            },
        },
        "required": ["action"],
    },
    "handler": None,  # override via run function
}


def run_process_monitor(parameters: dict, player=None, session_memory=None) -> str:
    """Handler for the process_monitor tool."""
    if not psutil:
        return outcome.failed("process_monitor", "psutil not installed")

    action = (parameters.get("action") or "").strip().lower()

    if action == "list":
        limit = parameters.get("limit", 50)
        return outcome.done("process_monitor", **_top(limit))

    if action == "top":
        return outcome.done("process_monitor", **_top(10))

    if action == "find":
        name = (parameters.get("name") or "").strip()
        if not name:
            return outcome.failed("process_monitor", "no 'name' provided for find")
        return outcome.done("process_monitor", **_find(name, 10))

    if action == "kill":
        pid = parameters.get("pid")
        name = parameters.get("name")
        return outcome.done("process_monitor", **_kill(pid, name))

    return outcome.failed("process_monitor", f"unknown action: {action}")


TOOL["handler"] = run_process_monitor
