"""actions/team_code_safety.py — JARVIS adapter for the Awesome LLM
team-code-safety service (apps/awesome-llm).

Exposes review_code / propose_fix / generate_docs as real HTTP calls against
the local FastAPI service. All changes are proposals only – never auto applied.
"""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import requests

from core import outcome
from core.app_manager import AppManager


AWESOME_LLM_URL = os.environ.get("JARVIS_AWESOME_LLM_URL", "http://127.0.0.1:7862").rstrip("/")
BASE_DIR = Path(__file__).resolve().parent.parent


def _validate_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("JARVIS_AWESOME_LLM_URL must be a loopback HTTP origin")
    return url


def _base_url() -> str:
    return _validate_url(AWESOME_LLM_URL)


def _http() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def _ensure_service() -> None:
    """Start the Awesome LLM service if it is not already running."""
    if not AppManager.is_awesome_llm_running():
        AppManager.start_awesome_llm()


def _read_code(file_path: str) -> str:
    path = Path(file_path)
    if not path.is_absolute():
        path = BASE_DIR / file_path
    if not path.exists():
        raise ValueError(f"File not found: {path}")
    return path.read_text(encoding="utf-8")


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Route team_code_safety actions to the Awesome LLM service."""
    try:
        action = (parameters.get("action") or "").lower()
        base = _base_url()

        if action == "start":
            return json.dumps(AppManager.start_awesome_llm(), ensure_ascii=False)
        if action == "stop":
            return json.dumps(AppManager.stop_awesome_llm(), ensure_ascii=False)

        if action not in {"review_code", "propose_fix", "generate_docs"}:
            return "team_code_safety actions: review_code, propose_fix, generate_docs"

        owner = parameters.get("owner") or "admin"
        file_path = parameters.get("file_path") or ""
        if not file_path:
            raise ValueError(f"{action} requires file_path")

        if action == "propose_fix":
            new_body = parameters.get("new_body")
            if not new_body:
                raise ValueError("propose_fix requires new_body")
            payload = {
                "owner": owner,
                "file_path": file_path,
                "instruction": parameters.get("instruction") or "",
                "new_body": new_body,
                "reason": parameters.get("reason") or "LLM refactor",
            }
            endpoint = f"{base}/refactor"
        else:
            payload = {
                "owner": owner,
                "file_path": file_path,
                "code": _read_code(file_path),
            }
            endpoint = f"{base}/review" if action == "review_code" else f"{base}/docgen"

        _ensure_service()
        resp = _http().post(endpoint, json=payload, timeout=(5, 60))
        if resp.status_code != 200:
            raise ValueError(f"Awesome LLM service returned HTTP {resp.status_code}: {resp.text}")

        return json.dumps({
            "status": "done",
            "action": action,
            "data": resp.json(),
        }, ensure_ascii=False)

    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        return outcome.failed("team_code_safety", str(exc),
                              hint="The Awesome LLM service starts automatically on first use; "
                                   "check apps/awesome-llm/ dependencies (fastapi, uvicorn).")


TOOL = {
    "name": "team_code_safety",
    "description": (
        "Safe LLM-assisted code modification for team members with owner scoping and git backup. "
        "review_code runs static safety checks on a file, propose_fix creates a code-change "
        "proposal (saved for review, never auto-applied), generate_docs drafts documentation. "
        "The Awesome LLM service starts automatically on first use."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "review_code | propose_fix | generate_docs | start | stop"},
            "owner": {"type": "STRING", "description": "Team member owner"},
            "file_path": {"type": "STRING", "description": "Relative file path"},
            "instruction": {"type": "STRING", "description": "Refactor instruction (propose_fix)"},
            "new_body": {"type": "STRING", "description": "Proposed replacement file content (propose_fix)"},
        },
        "required": ["action"]
    },
    "handler": run
}
