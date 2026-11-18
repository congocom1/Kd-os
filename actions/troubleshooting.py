"""
actions/troubleshooting.py — Auto-diagnosis and repair.

Walks the system, collects health metrics, diagnoses common issues, and
applies fixes where possible.
"""

import json
import logging
import os
import time
from pathlib import Path

from core import outcome
from core.lazyimport import installed

_psutil = installed("psutil")
psutil = None
if _psutil:
    import psutil

logger = logging.getLogger("troubleshooting")

# ── Health check ─────────────────────────────────────────────────────────────

def _collect_health() -> dict:
    """Collect all system health metrics into one report."""
    return {
        "cpu": {
            "percent": psutil.cpu_percent(interval=0.5),
            "load_average": os.sysconf("SC_LOADAVG") if hasattr(os, "sysconf") else None,
            "freq_mhz": psutil.cpu_freq().current if psutil.cpu_freq() else None,
        },
        "memory": {
            "percent": psutil.virtual_memory().percent,
            "used": psutil.virtual_memory().used,
            "total": psutil.virtual_memory().total,
        },
        "swap": {
            "percent": psutil.swap_memory().percent,
            "used": psutil.swap_memory().used,
        },
        "disk": {
            "root_percent": psutil.disk_usage("/").percent,
            "root_used": psutil.disk_usage("/").used,
        },
        "processes": {"running": len(psutil.pids()), "threads": 0},
        "network": {
            "bytes_sent": psutil.net_io_counters().bytes_sent,
            "bytes_recv": psutil.net_io_counters().bytes_recv,
        },
    }


def _diagnose() -> list[dict]:
    """Run diagnostics and return a list of findings with fixes."""
    findings = []

    # CPU temperature
    try:
        if os.path.exists("/sys/class/thermal/thermal_zone0/temp"):
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                temp = float(f.read().strip()) / 1000.0
            if temp > 85:
                findings.append({
                    "severity": "warning",
                    "topic": "CPU temperature",
                    "issue": f"CPU is hot at {temp:.1f}°C",
                    "fix": "Check cooling; run 'sudo cpupower frequency-set -g powersave'",
                })
    except Exception as e:
        logger.warning(f"Failed to read CPU temperature: {e}")

    # Disk space
    usage = psutil.disk_usage("/")
    if usage.percent > 90:
        findings.append({
            "severity": "critical",
            "topic": "Disk full",
            "issue": f"Root partition at {usage.percent:.1f}%",
            "fix": "Run 'sudo apt clean' or remove old logs",
        })

    # Heavy processes
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            procs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
            logger.debug(f"Failed to read process info: {e}")
    heavy = [p for p in procs if p.info["memory_percent"] > 50]
    if heavy:
        findings.append({
            "severity": "info",
            "topic": "Memory heavy processes",
            "issue": f"{len(heavy)} processes using >50% memory",
            "fix": f"IDs: {[p.info['pid'] for p in heavy][:5]}",
        })

    return findings


def _auto_remediate() -> list[str]:
    """Attempt to fix detected issues automatically."""
    fixes = []
    try:
        if psutil.disk_usage("/").percent > 90:
            log_dir = Path("/var/log")
            if log_dir.exists():
                for f in log_dir.glob("*.log"):
                    try:
                        if f.stat().st_size > 10 * 1024 * 1024:
                            f.unlink()
                            fixes.append(f"Removed {f.name} ({f.stat().st_size // 1024} KB)")
                    except (PermissionError, OSError) as exc:
                        logger.warning(f"Failed to remove log file: {exc}")
    except Exception as e:
        logger.error(f"Auto-remediation failed: {e}", exc_info=True)
        fixes.append(f"auto-remediation failed: {e}")

    return fixes


# ── Tool declaration ─────────────────────────────────────────────────────────

TOOL = {
    "name": "troubleshooting",
    "description": (
        "System diagnostics. Actions: health_check (full system diagnostics), "
        "diagnose (run diagnose and list findings with fixes), remediate "
        "(attempt automatic fixes for detected issues)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "health_check | diagnose | remediate",
            },
        },
        "required": ["action"],
    },
    "handler": None,
}


def run_troubleshooting(parameters: dict, player=None, session_memory=None) -> str:
    action = (parameters.get("action") or "").strip().lower()

    if action == "health_check":
        return outcome.done("troubleshooting", **_collect_health())

    if action == "diagnose":
        findings = _diagnose()
        lines = [f"[{i}] {f['severity'].upper()} — {f['topic']}: {f['issue']}"
                 for i, f in enumerate(findings, 1)]
        return outcome.done("troubleshooting", findings=lines)

    if action == "remediate":
        return outcome.done("troubleshooting", fixes=_auto_remediate())

    return outcome.failed("troubleshooting", f"unknown action: {action}")


TOOL["handler"] = run_troubleshooting
