"""
core/kernel_init.py — Bootstrapping for the JARVIS OS.

Populates:
  - signal handlers (SIGTERM/SIGINT → clean shutdown)
  - thread pool
  - process table
  - virtual file system mounts
  - device registry
  - notification center
  - system monitor, network monitor, storage monitor services
"""

from __future__ import annotations

import logging
import sys
import threading
import time

from core import os as kernel_os

logger = logging.getLogger("kernel_init")


def boot() -> None:
    """Run the OS bootstrap sequence."""
    if kernel_os.os._booted:
        return
    print("[JARVIS OS BOOT]")

    # 1. Register signal handlers for clean shutdown/reboot
    register_signals()
    kernel_os.os.boot()

    # 2. Mount standard directories
    mount_system_dirs()

    # 3. Register standard devices
    register_devices()

    # 4. Populate string dict (system identity)
    populate_string_dict()

    # 5. Start system services
    start_services()

    print("[JARVIS OS RUNNING]")


def register_signals() -> None:
    """Install clean shutdown/reboot handlers."""
    import signal

    def _shutdown(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        kernel_os.os.shutdown()
        raise SystemExit(0)

    def _reboot(signum, frame):
        logger.info("Reboot requested")
        kernel_os.os.reboot()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, _shutdown)


def mount_system_dirs() -> None:
    """Mount the standard directories as virtual volumes."""
    base = kernel_os.os.get_base_dir()
    mounts = {
        "home": base.parent / "home",
        "config": base / "config",
        "actions": base / "actions",
        "memory": base / "memory",
        "plugins": base / "plugins",
        "providers": base / "providers",
        "dashboard": base / "dashboard",
    }
    for name, path in mounts.items():
        try:
            path.mkdir(parents=True, exist_ok=True)
            kernel_os.os.mount(name, path)
        except Exception as e:
            logger.warning(f"mount {name}: {e}")


def register_devices() -> None:
    """Register standard OS devices."""
    kernel_os.os.add_device("camera", {"index": 0, "opened": False})
    kernel_os.os.add_device("microphone", {"index": 0})
    kernel_os.os.add_device("speaker", {"index": 0})
    kernel_os.os.add_device("network", {"interface": "eth0", "enabled": True})
    kernel_os.os.add_device("storage", {"total": 0, "used": 0, "free": 0})
    logger.info("Devices registered")


def populate_string_dict() -> None:
    """Write system identity to the string dict."""
    kernel_os.os.set("os_name", "JARVIS OS")
    kernel_os.os.set("version", "1.0.0")
    kernel_os.os.set("platform", sys.platform)
    kernel_os.os.set("cpu_count", str(__import__("os").cpu_count() or 1))
    kernel_os.os.set("python", sys.version.split()[0])
    logger.info("String dict populated")


def start_services() -> None:
    """Start all OS services."""
    logger.info("Starting system services...")

    # System monitor
    from actions.system_monitor import SystemMonitor
    monitor = SystemMonitor.start()
    monitor.configure(monitor.thresholds)
    threading.Thread(target=monitor.run, daemon=True, name="system-monitor").start()
    kernel_os.os.register_shutdown(monitor.stop)
    logger.info("  system_monitor started")

    # Network monitor
    start_network_monitor()

    # Storage service
    start_storage_service()

    # Notification service
    start_notification_service()

    # ProactiveEngine is driven by JarvisLive's session loop, not a service thread.


def start_network_monitor() -> None:
    """Launch a network monitoring background task."""
    import psutil

    def _observer() -> None:
        last_activity = 0.0
        while kernel_os.os._booted:
            try:
                net = psutil.net_io_counters()
                activity = net.bytes_sent + net.bytes_recv
                if activity > last_activity:
                    kernel_os.os.set(
                        "network.bytes_since_boot",
                        str(int(activity - last_activity)),
                    )
                last_activity = activity
            except Exception:
                pass
            time.sleep(5)

    thread = threading.Thread(target=_observer, daemon=True, name="net-monitor")
    thread.start()


def start_storage_service() -> None:
    """Seed storage stats into the string dict."""
    try:
        import shutil
        usage = shutil.disk_usage(kernel_os.os.get_base_dir())
        kernel_os.os.set("storage.total", str(usage.total))
        kernel_os.os.set("storage.free", str(usage.free))
    except Exception as e:
        logger.warning(f"storage: {e}")


def start_notification_service() -> None:
    """Placeholder for notification service registration."""
    import threading

    def _check() -> None:
        while kernel_os.os._booted:
            time.sleep(1)

    thread = threading.Thread(target=_check, daemon=True, name="notif-check")
    thread.start()
