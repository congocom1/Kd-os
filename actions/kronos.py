"""actions/kronos.py — JARVIS adapter for the local Kronos inference service.

Lets JARVIS run financial-market forecasts through Kronos without loading
PyTorch into the main JARVIS process.
"""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import requests

from core import outcome
from core.app_manager import AppManager


KRONOS_URL = os.environ.get("JARVIS_KRONOS_URL", "http://127.0.0.1:7861").rstrip("/")


def _validate_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("JARVIS_KRONOS_URL must be a loopback HTTP origin")
    return url


def _base_url() -> str:
    return _validate_url(KRONOS_URL)


def _http() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def _is_running() -> bool:
    try:
        return _http().get(f"{_base_url()}/health", timeout=2).status_code == 200
    except Exception:
        return False


def _ensure_service():
    """Start the Kronos service if it is not already running."""
    if not AppManager.is_kronos_running():
        AppManager.start_kronos()


def kronos(parameters: dict, player=None, session_memory=None) -> str:
    """Run Kronos financial-market forecasts from JARVIS."""
    try:
        action = parameters.get("action", "health")
        base = _base_url()

        if action == "health":
            _ensure_service()
            resp = _http().get(f"{base}/health", timeout=5)
            return json.dumps({"status": "done", "service": resp.json()}, ensure_ascii=False)

        if action == "models":
            _ensure_service()
            resp = _http().get(f"{base}/models", timeout=5)
            return json.dumps({"status": "done", "models": resp.json()}, ensure_ascii=False)

        if action == "start":
            result = AppManager.start_kronos()
            return json.dumps(result, ensure_ascii=False)

        if action == "stop":
            result = AppManager.stop_kronos()
            return json.dumps(result, ensure_ascii=False)

        if action != "predict":
            raise ValueError("action must be predict, health, models, start, or stop")

        csv_path = parameters.get("csv_path")
        csv_content = parameters.get("csv_content")
        if not csv_path and not csv_content:
            raise ValueError("predict requires csv_path or csv_content")

        if csv_path and not csv_content:
            path = Path(csv_path)
            if not path.is_absolute():
                path = Path(__file__).resolve().parent.parent / "data" / "shared" / csv_path
            if not path.exists():
                raise ValueError(f"CSV not found: {path}")
            csv_content = path.read_text(encoding="utf-8")

        payload = {
            "csv_content": csv_content,
            "lookback": int(parameters.get("lookback", 400)),
            "pred_len": int(parameters.get("pred_len", 120)),
            "columns": parameters.get("columns", ["open", "high", "low", "close", "volume", "amount"]),
            "timestamp_col": parameters.get("timestamp_col", "timestamps"),
            "T": float(parameters.get("T", 1.0)),
            "top_p": float(parameters.get("top_p", 0.9)),
            "sample_count": int(parameters.get("sample_count", 1)),
        }

        _ensure_service()
        resp = _http().post(f"{base}/predict", json=payload, timeout=(5, 120))
        if resp.status_code != 200:
            raise ValueError(f"Kronos service returned HTTP {resp.status_code}: {resp.text}")

        data = resp.json()
        # Summarize for spoken/text channel while keeping full forecast in `data`.
        forecast = data.get("forecast", [])
        summary = f"Forecast complete. {len(forecast)} predicted timesteps returned."
        if forecast:
            first = forecast[0]
            last = forecast[-1]
            summary += (
                f" First close {first.get('close', 'n/a')}, "
                f"last close {last.get('close', 'n/a')}."
            )

        return json.dumps({
            "status": "done",
            "summary": summary,
            "data": data,
        }, ensure_ascii=False)

    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        return outcome.failed("kronos", str(exc),
                              hint="Install Kronos deps with pip install -e '.[kronos]' and use action=start.")


TOOL = {
    "name": "kronos",
    "description": (
        "Run Kronos financial-market forecasts (K-line / OHLCV predictions). "
        "Use health/models to inspect the service, predict to forecast from CSV data. "
        "For predict, provide either csv_path (relative to data/shared/) or raw csv_content. "
        "The Kronos service starts automatically on first use if its Python dependencies are installed."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "One of: predict, health, models, start, stop",
            },
            "csv_path": {
                "type": "STRING",
                "description": "Path to OHLCV CSV, relative to data/shared/ (used when action=predict)",
            },
            "csv_content": {
                "type": "STRING",
                "description": "Raw CSV content as a string (alternative to csv_path)",
            },
            "lookback": {
                "type": "INTEGER",
                "description": "Number of input timesteps (default 400)",
            },
            "pred_len": {
                "type": "INTEGER",
                "description": "Number of future timesteps to predict (default 120)",
            },
            "columns": {
                "type": "ARRAY",
                "description": "OHLCV column names (default open,high,low,close,volume,amount)",
                "items": {"type": "STRING"},
            },
            "timestamp_col": {
                "type": "STRING",
                "description": "Name of timestamp column (default timestamps)",
            },
            "T": {
                "type": "NUMBER",
                "description": "Sampling temperature (default 1.0)",
            },
            "top_p": {
                "type": "NUMBER",
                "description": "Top-p nucleus sampling (default 0.9)",
            },
            "sample_count": {
                "type": "INTEGER",
                "description": "Number of forecast samples (default 1)",
            },
        },
        "required": ["action"],
    },
    "handler": kronos,
}
