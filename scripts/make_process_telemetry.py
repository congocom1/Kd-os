"""KD process/process telemetry integration and operational artefact."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

# Root of the repository (the place where the KD data folders live).
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.telemetry import get_telemetry
# Where the release-gate artefact is written.
ARTIFACT = ROOT / "artifacts" / "process_telemetry.json"

# Fields we consider 'process real-time information' for the release gate.
REQUIRED_PROCESS_FIELDS = (
    "cpu_percent",
    "memory_percent",
    "disk_percent",
    "network_bytes_sent",
    "network_bytes_recv",
    "gpu_utilization",
    "gpu_memory_used_mb",
    "gpu_memory_total_mb",
    "gpu_temperature_c",
)

# Only hardware/software facts are placed here - no personal data.
SENSITIVE_PATTERNS = (
    "api_key",
    "password",
    "secret",
    "token",
    "auth",
    "cookie",
    "private",
)


def _sanitise(obj: Any) -> Any:
    """Return a structure that never contains credential-like values."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            key = str(k).lower()
            if any(s in key for s in SENSITIVE_PATTERNS):
                out[k] = None
            else:
                out[k] = _sanitise(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [_sanitise(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def _build_snapshot() -> dict[str, Any]:
    """Create the real-time process block used by the release gate."""
    try:
        data = get_telemetry()
    except Exception as exc:  # pragma: no cover - safety net
        return {
            "snapshot_taken_at": time.time(),
            "status": "error",
            "error": type(exc).__name__,
            "process": {},
        }

    # Keep the keys that describe live process health.  Anything that looks like
    # a credential is zeroed out.
    safe = _sanitise(data)

    # The 'status' field also tells us whether the machine reported everything
    # correctly (ok / partial / offline).
    safe["snapshot_taken_at"] = time.time()
    safe["source_process"] = {
        "pid": data.get("process", {}).get("pid"),
        "comm": data.get("process", {}).get("name"),
        "cpu_percent": data.get("process", {}).get("cpu_percent"),
        "rss_mb": data.get("process", {}).get("memory_info", {}).get("rss", 0) / (1024 * 1024),
        "vms_mb": data.get("process", {}).get("memory_info", {}).get("vms", 0) / (1024 * 1024),
        "num_threads": data.get("process", {}).get("num_threads", 0),
    }
    return safe


def write_artefact() -> dict[str, Any]:
    """Create the release-gate artefact and return its content."""
    payload = _build_snapshot()
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    snapshot = write_artefact()
    print(json.dumps({"artefact": str(ARTIFACT), "snapshot_keys": sorted(snapshot.keys())}))


if __name__ == "__main__":
    main()
