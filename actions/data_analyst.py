"""actions/data_analyst.py — JARVIS adapter for the local data-analysis service.

Lets JARVIS answer questions about CSV/tabular data through the agno-based
data analyst agent (port of awesome-llm's ai_data_analysis_agent) running as
a separate FastAPI service, so agno/duckdb/pandas stay out of the main
JARVIS process. The service is started on demand from its own venv under
apps/data-analyst/.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

from core import outcome


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _get_base_dir()
SERVICE_DIR = BASE_DIR / "apps" / "data-analyst"
VENV_PYTHON = SERVICE_DIR / ".venv" / "bin" / "python"
SERVICE_LOG = BASE_DIR / "data" / "logs" / "data_analyst_service.log"

DATA_ANALYST_URL = os.environ.get("JARVIS_DATA_ANALYST_URL", "http://127.0.0.1:7863").rstrip("/")

_service_process = None


def _validate_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("JARVIS_DATA_ANALYST_URL must be a loopback HTTP origin")
    return url


def _base_url() -> str:
    return _validate_url(DATA_ANALYST_URL)


def _http() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def _is_running() -> bool:
    try:
        return _http().get(f"{_base_url()}/health", timeout=2).status_code == 200
    except Exception:
        return False


def _service_env() -> dict:
    """Environment for the service process.

    The assistant's provider config is passed through at launch via
    OPENAI_BASE_URL / OPENAI_API_KEY; the service itself defaults to a
    local Ollama endpoint when they are unset.
    """
    env = os.environ.copy()
    env.setdefault("OPENAI_BASE_URL", "http://localhost:11434/v1")
    env.setdefault("OPENAI_API_KEY", "ollama")
    return env


def _start_service() -> None:
    global _service_process
    if not VENV_PYTHON.exists():
        raise ValueError(
            f"data-analyst venv missing: {VENV_PYTHON}. "
            "Create it with: python3 -m venv apps/data-analyst/.venv && "
            "apps/data-analyst/.venv/bin/pip install -r apps/data-analyst/requirements.txt"
        )
    SERVICE_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = open(SERVICE_LOG, "ab", buffering=0)
    port = urlsplit(_base_url()).port or 7863
    _service_process = subprocess.Popen(
        [str(VENV_PYTHON), "-m", "uvicorn", "service:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(SERVICE_DIR),
        env=_service_env(),
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _ensure_service(timeout: float = 60.0) -> None:
    """Start the data-analyst service if needed and wait for /health."""
    if _is_running():
        return
    _start_service()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _service_process is not None and _service_process.poll() is not None:
            raise ValueError(
                f"data-analyst service exited with code {_service_process.returncode} "
                f"during startup; see {SERVICE_LOG}"
            )
        if _is_running():
            return
        time.sleep(0.5)
    raise ValueError(f"data-analyst service did not become healthy within {timeout:.0f}s; see {SERVICE_LOG}")


def analyze_data(parameters: dict, player=None, session_memory=None) -> str:
    """Answer a natural-language question about CSV/tabular data."""
    try:
        question = str(parameters.get("question", "")).strip()
        if not question:
            raise ValueError("analyze_data requires a non-empty 'question'")

        payload: dict = {"question": question}

        rows = parameters.get("rows")
        csv_path = parameters.get("csv_path")
        if rows:
            payload["rows"] = rows
        else:
            if not csv_path:
                raise ValueError("analyze_data requires csv_path or rows")
            path = Path(csv_path)
            if not path.is_absolute():
                path = BASE_DIR / "data" / "shared" / csv_path
            if not path.exists():
                raise ValueError(f"CSV not found: {path}")
            payload["csv_path"] = str(path)

        _ensure_service()
        base = _base_url()
        resp = _http().post(f"{base}/analyze", json=payload, timeout=(5, 300))
        if resp.status_code != 200:
            raise ValueError(f"data-analyst service returned HTTP {resp.status_code}: {resp.text[:500]}")

        data = resp.json()
        answer = str(data.get("answer", "")).strip()
        if not answer:
            return outcome.failed("analyze_data", "the agent returned an empty answer")

        tables = data.get("tables") or []
        table_name = tables[0].get("name") if tables else None
        row_count = tables[0].get("row_count") if tables else None
        return outcome.done("analyze_data",
                            answer=answer, table=table_name, rows=row_count)

    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        return outcome.failed("analyze_data", str(exc),
                              hint="The data-analyst service runs from apps/data-analyst/.venv; "
                                   "install its deps with apps/data-analyst/.venv/bin/pip install "
                                   "-r apps/data-analyst/requirements.txt")


TOOL = {
    "name": "analyze_data",
    "description": (
        "Answer a natural-language question about tabular data (CSV/Excel) using the "
        "local data-analysis agent (DuckDB + pandas over the uploaded table). "
        "Provide the question plus csv_path (relative to data/shared/, or absolute), "
        "or inline rows as a list of objects. "
        "The data-analyst service starts automatically on first use if its venv exists "
        "at apps/data-analyst/.venv."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "question": {
                "type": "STRING",
                "description": "Natural-language question about the data",
            },
            "csv_path": {
                "type": "STRING",
                "description": "Path to a CSV/Excel file, relative to data/shared/ (or absolute)",
            },
            "rows": {
                "type": "ARRAY",
                "description": "Inline tabular data as a list of row objects (alternative to csv_path)",
                "items": {"type": "OBJECT"},
            },
        },
        "required": ["question"],
    },
    "handler": analyze_data,
}
