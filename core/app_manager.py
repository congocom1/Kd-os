"""core/app_manager.py — Unified lifecycle manager for Mark-LVI sub-apps.

JARVIS owns the lifecycle of God's Eye View and Kronos. Each app stays in its
own process (avoiding dependency conflicts), but JARVIS can start, stop, and
health-check them on demand.
"""

from __future__ import annotations

import atexit
import logging
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from core.paths import get_base_dir as _get_base_dir

logger = logging.getLogger("jarvis.app_manager")

BASE_DIR = _get_base_dir()
GEV_DIR = BASE_DIR / "apps" / "gods-eye-view"
KRONOS_DIR = BASE_DIR / "apps" / "kronos"
AWESOME_LLM_DIR = BASE_DIR / "apps" / "awesome-llm"

GEV_URL = os.environ.get("JARVIS_GLOBE_URL", "http://127.0.0.1:4174")
KRONOS_URL = os.environ.get("JARVIS_KRONOS_URL", "http://127.0.0.1:7861")
AWESOME_LLM_URL = os.environ.get("JARVIS_AWESOME_LLM_URL", "http://127.0.0.1:7862")

# Module-level process handles so we can shut down what we started.
_processes: dict[str, Optional[subprocess.Popen]] = {
    "gev": None,
    "kronos": None,
    "awesome_llm": None,
}


def _is_port_open(url: str, timeout: float = 2.0) -> bool:
    """Return True if a local HTTP service is responding."""
    try:
        req = Request(url, headers={"User-Agent": "JARVIS-AppManager/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _kill_by_port(port: int) -> None:
    """Try to terminate any process listening on a local TCP port."""
    try:
        result = subprocess.run(
            ["lsof", "-t", "-i", f":{port}"],
            capture_output=True, text=True, timeout=5
        )
        for pid in result.stdout.strip().splitlines():
            if pid.isdigit():
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
    except Exception:
        pass


def _wait_for_service(url: str, attempts: int = 30, delay: float = 0.5,
                      process: subprocess.Popen | None = None) -> bool:
    """Poll a local URL until it responds, the child exits, or time runs out."""
    for _ in range(attempts):
        if process is not None and process.poll() is not None:
            return False
        if _is_port_open(url):
            return True
        time.sleep(delay)
    return False


class AppManager:
    """Start, stop, and health-check God's Eye View and Kronos."""

    @staticmethod
    def is_gev_running() -> bool:
        return _is_port_open(GEV_URL)

    @staticmethod
    def is_kronos_running() -> bool:
        return _is_port_open(f"{KRONOS_URL}/health")

    @classmethod
    def start_gev(cls) -> dict:
        """Start the God's Eye View Vite dev server if it is not already running."""
        if cls.is_gev_running():
            return {"status": "already_running", "url": GEV_URL}

        gev_dir = Path(os.environ.get("GODS_EYE_VIEW_DIR", GEV_DIR)).expanduser().resolve()
        local = gev_dir / "node_modules" / "vite" / "bin" / "vite.js"
        hoisted = BASE_DIR / "node_modules" / "vite" / "bin" / "vite.js"
        vite_bin = local if local.is_file() else hoisted
        if not vite_bin.is_file():
            return {"status": "failed", "reason": "Vite not installed. Run npm ci at the repository root."}

        node_name = "node.exe" if os.name == "nt" else "node"
        bundled_node = gev_dir / ".jarvis-runtime" / "node_modules" / "node" / "bin" / node_name
        node = shutil.which(str(bundled_node)) or shutil.which("node")
        if node is None:
            return {"status": "failed", "reason": "God's Eye View requires Node 24.14+ or 26."}
        cmd = [node, str(vite_bin), "--host", "127.0.0.1", "--port", "4174", "--strictPort"]
        try:
            # Unread stdout/stderr pipes can block a live dev server.
            proc = subprocess.Popen(cmd, cwd=gev_dir)
        except OSError as exc:
            logger.warning("Could not launch God's Eye View (%s)", type(exc).__name__)
            return {"status": "failed", "reason": "Could not launch God's Eye View."}
        _processes["gev"] = proc

        if _wait_for_service(GEV_URL, process=proc):
            return {"status": "started", "url": GEV_URL}

        cls.stop_gev()
        return {"status": "failed", "reason": "Server did not become ready; check the launch output."}

    @classmethod
    def stop_gev(cls) -> dict:
        """Stop only the globe process started by this manager."""
        proc = _processes.get("gev")
        if proc is None:
            return {"status": "not_managed", "reason": "No globe process started by this manager."}
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("Could not stop managed globe process (%s)", type(exc).__name__)
            return {"status": "failed", "reason": "Could not stop the managed globe process."}
        _processes["gev"] = None
        return {"status": "stopped"}

    @classmethod
    def ensure_gev(cls) -> dict:
        """Start GEV only if it is not already reachable."""
        return cls.start_gev() if not cls.is_gev_running() else {"status": "already_running", "url": GEV_URL}

    @classmethod
    def start_kronos(cls) -> dict:
        """Start the Kronos inference service if it is not already running."""
        if cls.is_kronos_running():
            return {"status": "already_running", "url": KRONOS_URL}

        service_file = KRONOS_DIR / "service.py"
        if not service_file.exists():
            return {
                "status": "failed",
                "reason": f"Kronos service file not found at {service_file}",
            }

        python_bin = os.environ.get("JARVIS_PYTHON", "python3")
        cmd = [python_bin, str(service_file), "--host", "127.0.0.1", "--port", "7861"]
        logger.info("Starting Kronos service: %s", " ".join(cmd))
        proc = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _processes["kronos"] = proc

        if _wait_for_service(f"{KRONOS_URL}/health"):
            return {"status": "started", "url": KRONOS_URL}

        cls.stop_kronos()
        return {"status": "failed", "reason": "Kronos service did not start in time"}

    @classmethod
    def stop_kronos(cls) -> dict:
        """Stop the Kronos service."""
        proc = _processes.get("kronos")
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            _processes["kronos"] = None

        _kill_by_port(7861)
        subprocess.run(["pkill", "-f", "kronos/service.py"], capture_output=True, timeout=3)
        return {"status": "stopped"}

    @classmethod
    def ensure_kronos(cls) -> dict:
        """Start Kronos only if it is not already reachable."""
        return cls.start_kronos() if not cls.is_kronos_running() else {"status": "already_running", "url": KRONOS_URL}

    @staticmethod
    def is_awesome_llm_running() -> bool:
        return _is_port_open(f"{AWESOME_LLM_URL}/health")

    @classmethod
    def start_awesome_llm(cls) -> dict:
        """Start the Awesome LLM team-code-safety service if not already running."""
        if cls.is_awesome_llm_running():
            return {"status": "already_running", "url": AWESOME_LLM_URL}

        service_file = AWESOME_LLM_DIR / "main.py"
        if not service_file.exists():
            return {"status": "failed",
                    "reason": f"Awesome LLM service not found at {service_file}"}

        venv_py = BASE_DIR / ".venv" / "bin" / "python"
        python_bin = os.environ.get(
            "JARVIS_PYTHON", str(venv_py) if venv_py.exists() else "python3")
        cmd = [python_bin, "-m", "uvicorn", "main:app",
               "--host", "127.0.0.1", "--port", "7862"]
        logger.info("Starting Awesome LLM service: %s", " ".join(cmd))
        proc = subprocess.Popen(
            cmd,
            cwd=str(AWESOME_LLM_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _processes["awesome_llm"] = proc

        if _wait_for_service(f"{AWESOME_LLM_URL}/health"):
            return {"status": "started", "url": AWESOME_LLM_URL}

        cls.stop_awesome_llm()
        return {"status": "failed", "reason": "Awesome LLM service did not start in time"}

    @classmethod
    def stop_awesome_llm(cls) -> dict:
        """Stop the Awesome LLM service."""
        proc = _processes.get("awesome_llm")
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            _processes["awesome_llm"] = None

        _kill_by_port(7862)
        subprocess.run(["pkill", "-f", "awesome-llm.*main:app"], capture_output=True, timeout=3)
        return {"status": "stopped"}

    @classmethod
    def ensure_awesome_llm(cls) -> dict:
        """Start the Awesome LLM service only if it is not already reachable."""
        return cls.start_awesome_llm() if not cls.is_awesome_llm_running() else {"status": "already_running", "url": AWESOME_LLM_URL}

    @classmethod
    def stop_all(cls) -> dict:
        """Stop every managed service."""
        return {
            "gev": cls.stop_gev(),
            "kronos": cls.stop_kronos(),
            "awesome_llm": cls.stop_awesome_llm(),
        }


def _cleanup_managed_services():
    """Stop only the services this process started (registered via atexit)."""
    for service in ("gev", "kronos", "awesome_llm"):
        proc = _processes.get(service)
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            _processes[service] = None


# Clean up services this process started when Python exits.
atexit.register(_cleanup_managed_services)
