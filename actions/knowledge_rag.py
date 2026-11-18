"""actions/knowledge_rag.py — JARVIS adapter for the knowledge-rag service.

A personal knowledge base: ingest documents/URLs/text into named collections,
then ask questions answered from those collections (retrieval + LLM). The
service lives in apps/knowledge-rag/ (ported from awesome-llm autonomous_rag,
Postgres/pgvector swapped for sqlite + numpy).
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


SERVICE_DIR = _get_base_dir() / "apps" / "knowledge-rag"
RAG_URL = os.environ.get("JARVIS_RAG_URL", "http://127.0.0.1:7864").rstrip("/")


def _base_url() -> str:
    parsed = urlsplit(RAG_URL)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("JARVIS_RAG_URL must be a loopback HTTP origin")
    return RAG_URL


def _http() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def _is_running() -> bool:
    try:
        return _http().get(f"{_base_url()}/health", timeout=2).status_code == 200
    except Exception:
        return False


def _ensure_service() -> None:
    if _is_running():
        return
    venv_py = SERVICE_DIR / ".venv" / "bin" / "python"
    if not venv_py.exists():
        raise ValueError(
            "knowledge-rag venv missing — run: python3 -m venv apps/knowledge-rag/.venv "
            "&& apps/knowledge-rag/.venv/bin/pip install -r apps/knowledge-rag/requirements.txt")
    log_path = _get_base_dir() / "data" / "logs" / "knowledge_rag_service.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "ab") as log:
        subprocess.Popen(
            [str(venv_py), "-m", "uvicorn", "service:app",
             "--host", "127.0.0.1", "--port", "7864"],
            cwd=str(SERVICE_DIR), stdout=log, stderr=log, start_new_session=True)
    for _ in range(60):
        if _is_running():
            return
        time.sleep(1)
    raise ValueError(f"knowledge-rag service did not start — see {log_path}")


def knowledge_rag(parameters: dict, player=None, session_memory=None) -> str:
    """Ingest knowledge and answer questions from it."""
    try:
        action = parameters.get("action", "query")
        base = _base_url()

        if action == "ingest":
            payload: dict = {"collection": parameters.get("collection", "default")}
            if parameters.get("path"):
                p = Path(parameters["path"])
                if not p.is_absolute():
                    p = _get_base_dir() / "data" / "shared" / p
                if not p.exists():
                    raise ValueError(f"not found: {p}")
                payload["path"] = str(p)
            elif parameters.get("url"):
                payload["url"] = parameters["url"]
            elif parameters.get("text"):
                payload["text"] = parameters["text"]
            else:
                raise ValueError("ingest requires path, url, or text")
            _ensure_service()
            resp = _http().post(f"{base}/ingest", json=payload, timeout=(5, 180))
            if resp.status_code != 200:
                raise ValueError(f"service returned HTTP {resp.status_code}: {resp.text}")
            data = resp.json()
            return json.dumps({
                "status": "done",
                "summary": (f"Ingested {data.get('chunks_added', 0)} chunks into "
                            f"collection '{data.get('collection')}' "
                            f"({data.get('total_chunks', 0)} total, mode {data.get('mode')})."),
                "data": data,
            }, ensure_ascii=False)

        if action == "query":
            question = (parameters.get("question") or "").strip()
            if not question:
                raise ValueError("query requires a question")
            _ensure_service()
            resp = _http().post(f"{base}/query", json={
                "question": question,
                "collection": parameters.get("collection", "default"),
                "k": int(parameters.get("k", 4)),
            }, timeout=(5, 180))
            if resp.status_code != 200:
                raise ValueError(f"service returned HTTP {resp.status_code}: {resp.text}")
            data = resp.json()
            sources = ", ".join({s.get("source", "?") for s in data.get("sources", [])})
            return json.dumps({
                "status": "done",
                "summary": f"{data.get('answer', '')} (sources: {sources or 'none'})",
                "data": data,
            }, ensure_ascii=False)

        if action == "health":
            _ensure_service()
            resp = _http().get(f"{base}/health", timeout=5)
            return json.dumps({"status": "done", "service": resp.json()}, ensure_ascii=False)

        raise ValueError("action must be ingest, query, or health")

    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        return outcome.failed("knowledge_rag", str(exc),
                              hint="The knowledge-rag service lives in apps/knowledge-rag/ "
                                   "and starts automatically once its venv exists.")


TOOL = {
    "name": "knowledge_rag",
    "description": (
        "Personal knowledge base powered by the awesome-llm autonomous RAG app. "
        "ingest documents (path relative to data/shared/, a URL, or raw text) into named "
        "collections, then query them — answers cite their sources. "
        "Use action=ingest to add knowledge, action=query to ask, action=health to inspect."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "One of: ingest, query, health",
            },
            "question": {
                "type": "STRING",
                "description": "The question to answer (action=query)",
            },
            "path": {
                "type": "STRING",
                "description": "Document path, relative to data/shared/ (action=ingest)",
            },
            "url": {
                "type": "STRING",
                "description": "Document URL (action=ingest)",
            },
            "text": {
                "type": "STRING",
                "description": "Raw text to ingest (action=ingest)",
            },
            "collection": {
                "type": "STRING",
                "description": "Knowledge collection name (default 'default')",
            },
            "k": {
                "type": "INTEGER",
                "description": "Chunks to retrieve per query (default 4)",
            },
        },
        "required": ["action"],
    },
    "handler": knowledge_rag,
}
