"""apps/knowledge-rag/service.py — headless port of the awesome-llm autonomous_rag app.

Original: awesome-llm-apps-main/rag_tutorials/autonomous_rag/autorag.py
(Streamlit + agno + pgvector/Postgres RAG agent). Same RAG loop — read a
document, chunk it, embed it, store it, then answer questions by retrieving
the top-k chunks and asking an LLM — with every heavyweight dependency
swapped out:

  Streamlit  -> FastAPI (this file), called by actions/knowledge_rag.py
  agno       -> plain requests to an OpenAI-compatible endpoint
  pgvector   -> sqlite (chunk metadata) + one .npy matrix per collection,
                cosine similarity computed in numpy

Chunking mirrors agno's default FixedSizeChunking used by
PDFUrlKnowledgeBase: chunk_size 5000 characters, overlap 200, sentence-aware
boundaries.

Embeddings come from the OpenAI-compatible embeddings endpoint named by
OPENAI_BASE_URL / OPENAI_API_KEY (default: local Ollama at
http://localhost:11434/v1 with model qwen3-embedding:0.6b). If the endpoint
is unreachable at ingest time, the collection falls back to a numpy-only
TF-IDF bag-of-words retriever, so the service still works fully offline.
"""

import argparse
import json
import math
import os
import re
import sqlite3
import time
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("KNOWLEDGE_DATA_DIR", APP_DIR / "data"))

OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://localhost:11434/v1").rstrip("/")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "ollama")
EMBED_MODEL = os.environ.get("KNOWLEDGE_EMBED_MODEL", "qwen3-embedding:0.6b")
CHAT_MODEL = os.environ.get("KNOWLEDGE_CHAT_MODEL", "qwen3.5:2b")

# agno FixedSizeChunking defaults, kept from the original knowledge base.
CHUNK_SIZE = 5000
CHUNK_OVERLAP = 200

DEFAULT_COLLECTION = "default"
DB_PATH = DATA_DIR / "chunks.db"

app = FastAPI(title="knowledge-rag")


# ── text extraction ──────────────────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return " ".join(" ".join(parser.parts).split())


def _pdf_to_text(raw: bytes) -> str:
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def _read_source(path: str | None, url: str | None, text: str | None) -> tuple[str, str]:
    """Return (text, source_label) for exactly one of path/url/text."""
    given = [s for s in (path, url, text) if s]
    if len(given) != 1:
        raise ValueError("provide exactly one of: path, url, text")

    if text:
        return text, "inline-text"

    if url:
        resp = requests.get(url, timeout=(5, 60), headers={"User-Agent": "knowledge-rag/1.0"})
        resp.raise_for_status()
        if url.lower().endswith(".pdf") or "pdf" in resp.headers.get("content-type", ""):
            return _pdf_to_text(resp.content), url
        return _html_to_text(resp.text), url

    p = Path(path).expanduser()
    if not p.is_file():
        raise ValueError(f"file not found: {p}")
    if p.suffix.lower() == ".pdf":
        return _pdf_to_text(p.read_bytes()), str(p)
    return p.read_text(encoding="utf-8", errors="replace"), str(p)


# ── chunking (agno FixedSizeChunking: size 5000, overlap 200, sentence-aware) ─

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _chunk(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = " ".join(text.split())
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # prefer to end on a sentence boundary within the window
            window = text[start:end]
            cuts = [m.end() for m in _SENTENCE_END.finditer(window)]
            if cuts:
                end = start + cuts[-1]
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


# ── storage: sqlite metadata + per-collection .npy vectors ───────────────────

def _db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS chunks ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  collection TEXT NOT NULL,"
        "  source TEXT NOT NULL,"
        "  text TEXT NOT NULL,"
        "  created REAL NOT NULL)"
    )
    return conn


def _collection_dir(collection: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", collection) or DEFAULT_COLLECTION
    d = DATA_DIR / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_meta(collection: str) -> dict:
    meta_path = _collection_dir(collection) / "meta.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    return {}


def _save_meta(collection: str, meta: dict) -> None:
    (_collection_dir(collection) / "meta.json").write_text(
        json.dumps(meta), encoding="utf-8"
    )


def _load_vectors(collection: str) -> np.ndarray | None:
    vec_path = _collection_dir(collection) / "vectors.npy"
    if vec_path.exists():
        return np.load(vec_path)
    return None


def _save_vectors(collection: str, matrix: np.ndarray) -> None:
    np.save(_collection_dir(collection) / "vectors.npy", matrix.astype(np.float32))


def _get_chunks(collection: str) -> list[dict]:
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT id, source, text FROM chunks WHERE collection = ? ORDER BY id",
            (collection,),
        ).fetchall()
        return [{"id": r[0], "source": r[1], "text": r[2]} for r in rows]
    finally:
        conn.close()


def _add_chunks(collection: str, source: str, texts: list[str]) -> None:
    conn = _db()
    try:
        conn.executemany(
            "INSERT INTO chunks (collection, source, text, created) VALUES (?, ?, ?, ?)",
            [(collection, source, t, time.time()) for t in texts],
        )
        conn.commit()
    finally:
        conn.close()


def _collections() -> list[dict]:
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT collection, COUNT(*) FROM chunks GROUP BY collection ORDER BY collection"
        ).fetchall()
        return [{"name": r[0], "chunks": r[1]} for r in rows]
    finally:
        conn.close()


# ── vector backends: remote embeddings, or numpy TF-IDF fallback ─────────────

def _embeddings_available() -> bool:
    try:
        resp = requests.post(
            f"{OPENAI_BASE_URL}/embeddings",
            json={"model": EMBED_MODEL, "input": "probe"},
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            timeout=(2, 15),
        )
        return resp.status_code == 200
    except requests.RequestException:
        return False


def _embed(texts: list[str]) -> np.ndarray:
    resp = requests.post(
        f"{OPENAI_BASE_URL}/embeddings",
        json={"model": EMBED_MODEL, "input": texts},
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        timeout=(5, 300),
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    data.sort(key=lambda d: d.get("index", 0))
    return np.array([d["embedding"] for d in data], dtype=np.float32)


_TOKEN = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _tfidf_matrix(texts: list[str], vocab: dict[str, int], idf: np.ndarray) -> np.ndarray:
    mat = np.zeros((len(texts), len(vocab)), dtype=np.float32)
    for i, text in enumerate(texts):
        for tok, count in Counter(_tokenize(text)).items():
            col = vocab.get(tok)
            if col is not None:
                mat[i, col] = count
    return mat * idf


def _tfidf_build(texts: list[str]) -> tuple[np.ndarray, dict]:
    docs = [Counter(_tokenize(t)) for t in texts]
    df: Counter = Counter()
    for doc in docs:
        for tok in doc:
            df[tok] += 1
    terms = sorted(df)
    vocab = {t: i for i, t in enumerate(terms)}
    n = len(texts)
    idf = np.array([math.log((1 + n) / (1 + df[t])) + 1.0 for t in terms], dtype=np.float32)
    return _tfidf_matrix(texts, vocab, idf), {"vocab": vocab, "idf": idf.tolist()}


def _vectorize_new_chunks(collection: str, new_texts: list[str]) -> tuple[np.ndarray | None, dict]:
    """Vectorize new chunks, keeping the collection in a single backend mode.

    Returns (new_vectors, meta). A TF-IDF collection returns None vectors and
    no fit — the caller re-fits over the full corpus so the idf stays
    consistent across ingests.
    """
    meta = _load_meta(collection)
    mode = meta.get("mode")

    if mode == "tfidf" or (mode is None and not _embeddings_available()):
        return None, {"mode": "tfidf"}

    vectors = _embed(new_texts)
    meta = {"mode": "embedding", "model": EMBED_MODEL, "dim": int(vectors.shape[1])}
    return vectors, meta


def _query_vector(collection: str, question: str) -> np.ndarray:
    meta = _load_meta(collection)
    if meta.get("mode") == "tfidf":
        vocab = {t: int(i) for t, i in meta["vocab"].items()}
        idf = np.array(meta["idf"], dtype=np.float32)
        return _tfidf_matrix([question], vocab, idf)[0]
    return _embed([question])[0]


def _top_k(matrix: np.ndarray, query: np.ndarray, k: int) -> list[tuple[int, float]]:
    m_norm = np.linalg.norm(matrix, axis=1, keepdims=True)
    m_norm[m_norm == 0] = 1e-12
    q_norm = np.linalg.norm(query) or 1e-12
    sims = (matrix / m_norm) @ (query / q_norm)
    idx = np.argsort(-sims)[:k]
    return [(int(i), float(sims[i])) for i in idx]


# ── LLM answering (mirrors the original agent's instructions) ───────────────

def _chat_available() -> bool:
    try:
        resp = requests.get(
            f"{OPENAI_BASE_URL}/models",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            timeout=(2, 5),
        )
        return resp.status_code == 200
    except requests.RequestException:
        return False


def _answer(question: str, contexts: list[dict]) -> str:
    context_block = "\n\n".join(
        f"[source: {c['source']}]\n{c['text']}" for c in contexts
    )
    payload = {
        "model": CHAT_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an autonomous RAG assistant. Search your knowledge "
                    "base first. Answer only from the retrieved context below. "
                    "Provide clear and concise answers. If the context does not "
                    "contain the answer, say so plainly.\n\n"
                    f"Context:\n{context_block}"
                ),
            },
            {"role": "user", "content": question},
        ],
        "temperature": 0.2,
        "stream": False,
    }
    resp = requests.post(
        f"{OPENAI_BASE_URL}/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        timeout=(5, 600),
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


# ── API ──────────────────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    path: str | None = None
    url: str | None = None
    text: str | None = None
    collection: str = DEFAULT_COLLECTION


class QueryRequest(BaseModel):
    question: str
    collection: str = DEFAULT_COLLECTION
    k: int = 3  # original used num_documents=3


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "knowledge-rag",
        "embeddings_backend": f"{OPENAI_BASE_URL} model={EMBED_MODEL}",
        "embeddings_available": _embeddings_available(),
        "chat_model": CHAT_MODEL,
        "chat_available": _chat_available(),
        "collections": _collections(),
    }


@app.post("/ingest")
def ingest(req: IngestRequest):
    try:
        text, source = _read_source(req.path, req.url, req.text)
    except (ValueError, OSError, requests.RequestException) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    chunks = _chunk(text)
    if not chunks:
        raise HTTPException(status_code=400, detail="source produced no text to ingest")

    vectors, meta = _vectorize_new_chunks(req.collection, chunks)

    existing = _load_vectors(req.collection)
    if meta["mode"] == "tfidf":
        # tfidf is re-fit over the full corpus on every ingest: rebuild the
        # matrix and persist the fit so query-time vectorization matches
        all_texts = [c["text"] for c in _get_chunks(req.collection)] + chunks
        matrix, fit = _tfidf_build(all_texts)
        meta = {**meta, **fit}
    else:
        matrix = np.vstack([existing, vectors]) if existing is not None else vectors

    _save_vectors(req.collection, matrix)
    _save_meta(req.collection, meta)
    _add_chunks(req.collection, source, chunks)

    return {
        "status": "ok",
        "collection": req.collection,
        "source": source,
        "chunks_added": len(chunks),
        "total_chunks": len(_get_chunks(req.collection)),
        "mode": meta["mode"],
    }


@app.post("/query")
def query(req: QueryRequest):
    chunks = _get_chunks(req.collection)
    matrix = _load_vectors(req.collection)
    if not chunks or matrix is None:
        return {
            "answer": "",
            "sources": [],
            "error": f"collection '{req.collection}' is empty — ingest something first",
        }

    qvec = _query_vector(req.collection, req.question)
    hits = _top_k(matrix, qvec, max(1, req.k))
    contexts = [
        {**chunks[i], "score": round(score, 4)} for i, score in hits if i < len(chunks)
    ]

    answer = _answer(req.question, contexts)
    sources = [
        {
            "source": c["source"],
            "chunk_id": c["id"],
            "score": c["score"],
            "snippet": c["text"][:240],
        }
        for c in contexts
    ]
    return {"answer": answer, "sources": sources, "collection": req.collection}


@app.get("/collections")
def collections():
    return {"collections": _collections()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("KNOWLEDGE_PORT", "7864")))
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
