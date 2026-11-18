"""Read-only KD baseline: no model loading, capture, config reads or installs.

Run from the repository: python -m core.diagnostics
Installed packages and reachable APIs are not proof of working inference.
"""
from __future__ import annotations

import importlib.metadata
import json
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

import psutil


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def ollama_inventory() -> dict:
    """Probe only loopback; ignore proxy environment and refuse redirects."""
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open("http://127.0.0.1:11434/api/tags", timeout=3) as response:
            raw = response.read(1_048_577)
        if len(raw) > 1_048_576:
            return {"status": "error", "reason": "response_too_large"}
        data = json.loads(raw)
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, list):
            return {"status": "error", "reason": "invalid_response"}
        names = sorted({m["name"] for m in models if isinstance(m, dict)
                        and isinstance(m.get("name"), str)})
        return {"status": "reachable", "models": names, "inference": "not_tested"}
    except (OSError, ValueError):
        # Do not echo response bodies or exception strings into reports.
        return {"status": "unavailable", "inference": "not_tested"}


def gpu_inventory() -> dict:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return {"status": "unavailable", "reason": "nvidia_smi_missing"}
    try:
        result = subprocess.run(
            [executable, "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if result.returncode:
            return {"status": "unavailable", "reason": "query_failed"}
        devices = []
        for line in result.stdout.splitlines():
            name, memory, driver = (part.strip() for part in line.rsplit(",", 2))
            devices.append({"name": name, "memory_mib": int(memory), "driver": driver})
        return {"status": "detected" if devices else "unavailable",
                "devices": devices, "inference": "not_tested"}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"status": "unavailable", "reason": "query_failed"}


def collect() -> dict:
    packages = {}
    for name in ("fastapi", "PyQt6", "faster-whisper", "piper-tts",
                 "sounddevice", "onnxruntime", "onnxruntime-gpu", "torch"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "schema_version": "1.0", "observed_at": datetime.now(timezone.utc).isoformat(),
        "system": {"os": platform.system(), "release": platform.release(),
                   "python": platform.python_version(), "cpu_count": psutil.cpu_count(),
                   "ram_bytes": psutil.virtual_memory().total},
        "tools_on_path": {name: shutil.which(name) is not None for name in
                          ("ollama", "docker", "nvcc", "gnat", "gnatprove", "sbcl",
                           "gcc", "g++", "cmake", "node", "npm")},
        "packages": packages, "gpu": gpu_inventory(), "ollama": ollama_inventory(),
        "not_tested": ["microphone_capture", "speech_recognition", "speech_synthesis",
                       "gpu_inference", "docker_daemon", "authorization_coverage",
                       "backup_restore", "gui_rendering"],
    }


def main() -> None:
    print(json.dumps(collect(), indent=2))


if __name__ == "__main__":
    main()