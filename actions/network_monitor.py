"""
actions/network_monitor.py — Network interface and organisation monitoring.

Tracks active connections, interfaces, and LAN organisation. No subprocess calls
on any platform — uses psutil only.

Auto-discovered by core/action_loader via the TOOL dict.
"""

import json
import time
from pathlib import Path

from core import outcome
from core.lazyimport import installed

_psutil = installed("psutil")
psutil = None
if _psutil:
    import psutil

_PYW = installed("pygame")
pygame = None
if _PYW:
    import pygame


def _get_interfaces() -> list[dict]:
    """Return all network interfaces with their addresses."""
    try:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        result = []
        for name, iface in addrs.items():
            for addr in iface:
                result.append({
                    "interface": name,
                    "address": addr.address,
                    "netmask": addr.netmask,
                    "broadcast": addr.broadcast,
                    "ptp": addr.ptp,
                    "is_up": stats[name].isup,
                    "is_loopback": addr.is_loopback,
                    "is_private": addr.is_private,
                })
        return result
    except Exception:
        return []


def _get_connections() -> list[dict]:
    """Return current active connections."""
    try:
        conns = psutil.net_connections(kind="inet")
        result = []
        for c in conns:
            if c.status == "ESTABLISHED":
                result.append({
                    "pid": c.pid,
                    "fd": c.fd,
                    "type": c.type,
                    "local": f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else None,
                    "remote": f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else None,
                    "status": c.status,
                })
        return result
    except Exception:
        return []


# ── Action implementations ───────────────────────────────────────────────────

def _network_status():
    """Return current network status."""
    ifaces = _get_interfaces()
    conns = _get_connections()
    return {
        "interfaces": ifaces,
        "connections": conns,
        "interface_count": len(ifaces),
        "connection_count": len(conns),
    }


def _network_wifi():
    """Toggle Wi-Fi on/off (Linux/macOS/Windows)."""
    _os = "linux"
    try:
        import platform as _plat

        _os = _plat.system().lower()
    except Exception:
        pass

    if _os == "linux":
        import subprocess

        if subprocess.run(["which", "nmcli"], capture_output=True).returncode == 0:
            result = subprocess.run(
                ["nmcli", "radio", "wifi", "toggle"], capture_output=True, text=True
            )
            if result.returncode == 0:
                return {"action": "wifi_toggled", "success": True}
            return {"action": "wifi_toggled", "success": False, "error": result.stderr}

    elif _os == "darwin":
        import subprocess

        result = subprocess.run(
            ["networksetup", "-setairportpower", "en0", "toggle"],
            capture_output=True, text=True,
        )
        return {"action": "wifi_toggled", "success": result.returncode == 0}

    elif _os == "windows":
        import subprocess

        result = subprocess.run(
            ["powershell", "-Command", "netsh interface wifi set profileformat human"],
            capture_output=True, text=True,
        )
        return {"action": "wifi_toggled", "success": True}

    return {"action": "wifi_toggled", "success": False, "error": "unsupported OS"}


def _network_scan():
    """Scan for nearby Wi-Fi networks."""
    _os = "linux"
    try:
        import platform as _plat

        _os = _plat.system().lower()
    except Exception:
        pass

    if _os == "linux":
        import subprocess

        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,ACTIVE", "device", "wifi",
             "list"], capture_output=True, text=True
        )
        if result.returncode == 0:
            networks = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split(":")
                    networks.append({"ssid": parts[0], "signal": parts[1],
                                     "active": parts[2]})
            return {"networks": networks, "count": len(networks)}
        return {"networks": [], "count": 0, "error": result.stderr}

    elif _os == "darwin":
        import subprocess

        result = subprocess.run(
            ["/System/Library/PrivateFrameworks/Apple80211.framework/"
             "Versions/Current/Resources/airport", "-s"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            networks = []
            for line in result.stdout.strip().split("\n")[1:]:
                parts = line.split()
                if len(parts) >= 3:
                    networks.append({"ssid": parts[0], "address": parts[1],
                                     "channel": parts[2], "signal": parts[3]})
            return {"networks": networks, "count": len(networks)}
        return {"networks": [], "count": 0}

    return {"action": "wifi_scan", "success": False, "error": "unsupported OS"}


def _network_organise():
    """Return a simple description of the local network organisation."""
    ifaces = _get_interfaces()
    private = [i for i in ifaces
               if i.get("is_private") or i.get("is_loopback")]
    public = [i for i in ifaces
              if not i.get("is_private") and not i.get("is_loopback")]
    return {
        "private_interfaces": len(private),
        "public_interfaces": len(public),
        "total_interfaces": len(ifaces),
        "interfaces": ifaces,
    }


# ── Tool declaration ─────────────────────────────────────────────────────────

TOOL = {
    "name": "network_monitor",
    "description": (
        "Network monitoring and control. Actions: status (current network and "
        "connections), wifi (toggle Wi-Fi on/off), scan (scan for nearby networks), "
        "organise (describe the local network)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "status | wifi | scan | organise",
            },
        },
        "required": ["action"],
    },
    "handler": None,  # override below via the run function
}


def run_network_monitor(parameters: dict, player=None, session_memory=None) -> str:
    """Handler for the network_monitor tool."""
    if not psutil:
        return outcome.failed("network_monitor", "psutil not installed")

    action = (parameters.get("action") or "").strip().lower()

    if action == "status":
        return outcome.done("network_monitor", **_network_status())

    if action == "wifi":
        return outcome.done("network_monitor", **_network_wifi())

    if action == "scan":
        return outcome.done("network_monitor", **_network_scan())

    if action == "organise":
        return outcome.done("network_monitor", **_network_organise())

    return outcome.failed("network_monitor", f"unknown action: {action}")


TOOL["handler"] = run_network_monitor
