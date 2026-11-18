"""
providers/rag.py — RAG (Retrieval-Augmented Generation) provider for KD.

Integrates with the knowledge-rag service and provides a clean interface for
document ingestion, retrieval, and RAG-enhanced LLM queries.

Features:
- Multiple retrieval strategies (dense, sparse, hybrid)
- Reranking with cross-encoders
- Semantic chunking
- Knowledge graph extraction
- Collection management
- Source citation and provenance
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np
import requests

from .base import DEFAULT_CAPS, Field
from .llm_openai import OpenAICompatLLM
from .llm_router import LLMRouter

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

APP_DIR = Path(__file__).resolve().parent.parent / "apps" / "knowledge-rag"
DATA_DIR = Path(os.environ.get("KNOWLEDGE_DATA_DIR", APP_DIR / "data"))

RAG_SERVICE_URL = os.environ.get("JARVIS_RAG_URL", "http://127.0.0.1:7864").rstrip("/")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://localhost:11434/v1").rstrip("/")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "ollama")
EMBED_MODEL = os.environ.get("KNOWLEDGE_EMBED_MODEL", "qwen3-embedding:0.6b")
RERANK_MODEL = os.environ.get("KNOWLEDGE_RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

CHUNK_SIZE = 5000
CHUNK_OVERLAP = 200

# ─────────────────────────────────────────────────────────────────────────────
# Data Classes
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Chunk:
    """A document chunk with metadata."""
    id: int
    text: str
    source: str
    collection: str
    metadata: dict = field(default_factory=dict)
    embedding: np.ndarray | None = None


@dataclass
class RetrievalResult:
    """Result of a retrieval operation."""
    chunks: list[Chunk]
    scores: list[float]
    query: str
    collection: str
    retrieval_time_ms: float


@dataclass
class RAGResponse:
    """Complete RAG response with answer and sources."""
    answer: str
    sources: list[dict]
    collection: str
    retrieval_time_ms: float
    generation_time_ms: float
    confidence: float


# ─────────────────────────────────────────────────────────────────────────────
# Chunking Strategies
# ─────────────────────────────────────────────────────────────────────────────


def chunk_text_fixed(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Fixed-size chunking with sentence-aware boundaries (agno-style)."""
    if not text.strip():
        return []

    # Split into sentences first
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    current_chunk = []
    current_len = 0

    for sent in sentences:
        sent_len = len(sent)
        if current_len + sent_len > chunk_size and current_chunk:
            chunk_text = " ".join(current_chunk)
            chunks.append(chunk_text)
            # Keep overlap
            overlap_text = " ".join(current_chunk[-3:]) if len(current_chunk) > 3 else chunk_text
            current_chunk = [overlap_text] if len(overlap_text) < chunk_size else []
            current_len = len(overlap_text) if current_chunk else 0

        current_chunk.append(sent)
        current_len += sent_len + 1

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks


def chunk_text_semantic(text: str, max_chunk_size: int = CHUNK_SIZE) -> list[str]:
    """Semantic chunking using sentence embeddings (requires sentence-transformers)."""
    try:
        from sentence_transformers import SentenceTransformer, util

        model = SentenceTransformer('all-MiniLM-L6-v2')
        sentences = re.split(r'(?<=[.!?])\s+', text)
        if len(sentences) <= 1:
            return [text] if text.strip() else []

        embeddings = model.encode(sentences)
        chunks = []
        current_chunk = [sentences[0]]

        for i in range(1, len(sentences)):
            # Check similarity with previous sentence
            sim = util.cos_sim(embeddings[i-1:i], embeddings[i:i+1]).item()
            # If similarity drops significantly, start new chunk
            if sim < 0.3 and len(" ".join(current_chunk)) > 100:
                chunks.append(" ".join(current_chunk))
                current_chunk = [sentences[i]]
            else:
                current_chunk.append(sentences[i])

            # Hard limit
            if len(" ".join(current_chunk)) > max_chunk_size:
                chunks.append(" ".join(current_chunk))
                current_chunk = []

        if current_chunk:
            chunks.append(" ".join(current_chunk))

        return chunks
    except Exception:
        # Fallback to fixed chunking
        return chunk_text_fixed(text)


# ─────────────────────────────────────────────────────────────────────────────
# Embedding Provider
# ─────────────────────────────────────────────────────────────────────────────


class EmbeddingProvider:
    """Unified embedding provider supporting multiple backends."""

    def __init__(self, base_url: str = OPENAI_BASE_URL, api_key: str = OPENAI_API_KEY,
                 model: str = EMBED_MODEL):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self._session = requests.Session()
        self._session.trust_env = False
        self._local_model = None

    def _embed_remote(self, texts: list[str]) -> np.ndarray:
        """Embed using OpenAI-compatible endpoint."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {"model": self.model, "input": texts}
        resp = self._session.post(f"{self.base_url}/embeddings", json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        embeddings = [d["embedding"] for d in data["data"]]
        return np.array(embeddings, dtype=np.float32)

    def _embed_local(self, texts: list[str]) -> np.ndarray:
        """Embed using local sentence-transformers."""
        if self._local_model is None:
            from sentence_transformers import SentenceTransformer
            self._local_model = SentenceTransformer('all-MiniLM-L6-v2')
        return self._local_model.encode(texts, convert_to_numpy=True)

    def embed(self, texts: list[str]) -> np.ndarray:
        """Embed texts, trying remote first then local."""
        if isinstance(texts, str):
            texts = [texts]
        try:
            return self._embed_remote(texts)
        except Exception:
            return self._embed_local(texts)

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


# ─────────────────────────────────────────────────────────────────────────────
# Reranker
# ─────────────────────────────────────────────────────────────────────────────


class Reranker:
    """Cross-encoder reranker for improved retrieval quality."""

    def __init__(self, model_name: str = RERANK_MODEL):
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.model_name)

    def rerank(self, query: str, chunks: list[Chunk], top_k: int = 5) -> list[tuple[Chunk, float]]:
        """Rerank chunks by relevance to query."""
        if not chunks:
            return []

        self._load()
        pairs = [(query, chunk.text) for chunk in chunks]
        scores = self._model.predict(pairs)

        ranked = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]


# ─────────────────────────────────────────────────────────────────────────────
# Vector Store (SQLite + NumPy)
# ─────────────────────────────────────────────────────────────────────────────


class VectorStore:
    """Local vector store using SQLite for metadata and .npy for embeddings."""

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = data_dir / "chunks.db"
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection TEXT NOT NULL,
                    text TEXT NOT NULL,
                    source TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}',
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_collection ON chunks(collection)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_source ON chunks(source)
            """)

    def _vectors_path(self, collection: str) -> Path:
        return self.data_dir / f"{collection}_vectors.npy"

    def _meta_path(self, collection: str) -> Path:
        return self.data_dir / f"{collection}_meta.json"

    def add_chunks(self, collection: str, chunks: list[Chunk]) -> list[int]:
        """Add chunks and return their IDs."""
        with sqlite3.connect(self.db_path) as conn:
            ids = []
            for chunk in chunks:
                cur = conn.execute(
                    "INSERT INTO chunks (collection, text, source, metadata) VALUES (?, ?, ?, ?)",
                    (collection, chunk.text, chunk.source, json.dumps(chunk.metadata))
                )
                ids.append(cur.lastrowid)
            conn.commit()
        return ids

    def get_chunks(self, collection: str) -> list[Chunk]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, text, source, metadata FROM chunks WHERE collection = ?",
                (collection,)
            ).fetchall()
            return [Chunk(
                id=row["id"],
                text=row["text"],
                source=row["source"],
                collection=collection,
                metadata=json.loads(row["metadata"])
            ) for row in rows]

    def save_vectors(self, collection: str, vectors: np.ndarray):
        np.save(self._vectors_path(collection), vectors)

    def load_vectors(self, collection: str) -> np.ndarray | None:
        path = self._vectors_path(collection)
        if path.exists():
            return np.load(path)
        return None

    def save_meta(self, collection: str, meta: dict):
        with open(self._meta_path(collection), "w") as f:
            json.dump(meta, f)

    def load_meta(self, collection: str) -> dict:
        path = self._meta_path(collection)
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return {"mode": "dense"}

    def list_collections(self) -> list[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT DISTINCT collection FROM chunks").fetchall()
            return [r[0] for r in rows]

    def delete_collection(self, collection: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM chunks WHERE collection = ?", (collection,))
            conn.commit()
        for path in [self._vectors_path(collection), self._meta_path(collection)]:
            if path.exists():
                path.unlink()

    def get_stats(self, collection: str) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE collection = ?", (collection,)
            ).fetchone()[0]
        vectors = self.load_vectors(collection)
        return {
            "collection": collection,
            "chunk_count": count,
            "vector_shape": vectors.shape if vectors is not None else None,
            "has_vectors": vectors is not None,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Retrieval Engine
# ─────────────────────────────────────────────────────────────────────────────


class RetrievalEngine:
    """Multi-strategy retrieval engine."""

    def __init__(self, vector_store: VectorStore, embedder: EmbeddingProvider,
                 reranker: Reranker | None = None):
        self.store = vector_store
        self.embedder = embedder
        self.reranker = reranker

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """Compute cosine similarity between query vector and matrix."""
        a_norm = np.linalg.norm(a)
        b_norm = np.linalg.norm(b, axis=1)
        if a_norm == 0 or np.any(b_norm == 0):
            return np.zeros(len(b_norm))
        return (b @ a) / (b_norm * a_norm)

    def _bm25_search(self, query: str, chunks: list[Chunk], top_k: int) -> list[tuple[int, float]]:
        """BM25 sparse retrieval fallback."""
        try:
            from rank_bm25 import BM25Okapi
            corpus = [chunk.text.split() for chunk in chunks]
            bm25 = BM25Okapi(corpus)
            scores = bm25.get_scores(query.split())
            top_indices = np.argsort(scores)[::-1][:top_k]
            return [(int(i), float(scores[i])) for i in top_indices if scores[i] > 0]
        except Exception:
            return []

    def retrieve(self, query: str, collection: str, top_k: int = 5,
                 strategy: str = "hybrid") -> RetrievalResult:
        """Retrieve relevant chunks for a query."""
        start = time.perf_counter()

        chunks = self.store.get_chunks(collection)
        if not chunks:
            return RetrievalResult([], [], query, collection,
                                   (time.perf_counter() - start) * 1000)

        vectors = self.store.load_vectors(collection)
        meta = self.store.load_meta(collection)

        # Get query embedding
        qvec = self.embedder.embed_one(query)

        # Dense retrieval
        dense_scores = []
        if vectors is not None and meta.get("mode") != "tfidf":
            dense_scores = self._cosine_similarity(qvec, vectors)
        elif meta.get("mode") == "tfidf":
            # TF-IDF mode - use stored vectorizer
            from sklearn.feature_extraction.text import TfidfVectorizer
            if "tfidf_vocab" in meta and "tfidf_idf" in meta:
                vec = TfidfVectorizer(vocabulary=meta["tfidf_vocab"])
                vec.idf_ = np.array(meta["tfidf_idf"])
                qvec_tfidf = vec.transform([query])
                doc_tfidf = vec.transform([c.text for c in chunks])
                dense_scores = (qvec_tfidf @ doc_tfidf.T).toarray()[0]
            else:
                dense_scores = np.zeros(len(chunks))

        # Sparse retrieval (BM25)
        sparse_scores = np.zeros(len(chunks))
        if strategy in ("hybrid", "sparse"):
            bm25_results = self._bm25_search(query, chunks, top_k * 2)
            for idx, score in bm25_results:
                sparse_scores[idx] = score
            # Normalize
            if sparse_scores.max() > 0:
                sparse_scores = sparse_scores / sparse_scores.max()

        # Combine scores
        if strategy == "hybrid":
            combined = 0.7 * dense_scores + 0.3 * sparse_scores
        elif strategy == "dense":
            combined = dense_scores
        else:
            combined = sparse_scores

        # Get top-k
        top_indices = np.argsort(combined)[::-1][:top_k * 2]  # Get more for reranking
        top_chunks = [chunks[i] for i in top_indices]
        top_scores = [float(combined[i]) for i in top_indices]

        # Rerank if available
        if self.reranker and top_chunks:
            reranked = self.reranker.rerank(query, top_chunks, top_k)
            top_chunks = [c for c, _ in reranked]
            top_scores = [s for _, s in reranked]

        return RetrievalResult(
            chunks=top_chunks[:top_k],
            scores=top_scores[:top_k],
            query=query,
            collection=collection,
            retrieval_time_ms=(time.perf_counter() - start) * 1000
        )


# ─────────────────────────────────────────────────────────────────────────────
# RAG Provider
# ─────────────────────────────────────────────────────────────────────────────


class RAGProvider:
    """Main RAG provider integrating retrieval with LLM generation."""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.data_dir = Path(cfg.get("data_dir", DATA_DIR))
        self.embedder = EmbeddingProvider(
            base_url=cfg.get("embed_base_url", OPENAI_BASE_URL),
            api_key=cfg.get("embed_api_key", OPENAI_API_KEY),
            model=cfg.get("embed_model", EMBED_MODEL)
        )
        self.reranker = Reranker(cfg.get("rerank_model", RERANK_MODEL))
        self.store = VectorStore(self.data_dir)
        self.retriever = RetrievalEngine(self.store, self.embedder, self.reranker)

        # LLM for answer generation
        self.llm = OpenAICompatLLM({
            "base_url": cfg.get("chat_base_url", OPENAI_BASE_URL),
            "model": cfg.get("chat_model", "qwen3.5:2b"),
            "api_key": cfg.get("chat_api_key", OPENAI_API_KEY),
        })

        # RAG service URL for delegation
        self.service_url = cfg.get("service_url", RAG_SERVICE_URL)

    def ingest(self, text: str, source: str, collection: str = "default",
               chunking: str = "semantic", metadata: dict | None = None) -> dict:
        """Ingest text into a collection."""
        if chunking == "semantic":
            chunk_texts = chunk_text_semantic(text)
        else:
            chunk_texts = chunk_text_fixed(text)

        if not chunk_texts:
            return {"status": "error", "message": "No text to ingest"}

        # Create chunks
        chunks = []
        for i, ct in enumerate(chunk_texts):
            chunk_meta = metadata or {}
            chunk_meta.update({"chunk_index": i, "total_chunks": len(chunk_texts)})
            chunks.append(Chunk(
                id=0,  # Will be assigned by store
                text=ct,
                source=source,
                collection=collection,
                metadata=chunk_meta
            ))

        # Embed chunks
        texts = [c.text for c in chunks]
        embeddings = self.embedder.embed(texts)
        for chunk, emb in zip(chunks, embeddings):
            chunk.embedding = emb

        # Store
        ids = self.store.add_chunks(collection, chunks)
        for chunk, cid in zip(chunks, ids):
            chunk.id = cid

        # Save vectors
        vectors = np.vstack([c.embedding for c in chunks])
        existing = self.store.load_vectors(collection)
        if existing is not None:
            vectors = np.vstack([existing, vectors])
        self.store.save_vectors(collection, vectors)

        return {
            "status": "ok",
            "collection": collection,
            "source": source,
            "chunks_added": len(chunks),
            "total_chunks": len(self.store.get_chunks(collection)),
        }

    def ingest_file(self, path: str, collection: str = "default") -> dict:
        """Ingest a file (PDF, text, HTML)."""
        p = Path(path)
        if not p.exists():
            return {"status": "error", "message": f"File not found: {path}"}

        if p.suffix.lower() == ".pdf":
            import io
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(p.read_bytes()))
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        elif p.suffix.lower() in (".html", ".htm"):
            from html.parser import HTMLParser

            class Extractor(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.parts = []
                    self._skip = 0
                def handle_starttag(self, tag, attrs):
                    if tag in ("script", "style"): self._skip += 1
                def handle_endtag(self, tag):
                    if tag in ("script", "style") and self._skip: self._skip -= 1
                def handle_data(self, data):
                    if not self._skip: self.parts.append(data)
            parser = Extractor()
            parser.feed(p.read_text(encoding="utf-8", errors="ignore"))
            text = " ".join(" ".join(parser.parts).split())
        else:
            text = p.read_text(encoding="utf-8", errors="ignore")

        return self.ingest(text, str(p), collection)

    def ingest_url(self, url: str, collection: str = "default") -> dict:
        """Ingest content from a URL."""
        try:
            resp = requests.get(url, timeout=30, headers={"User-Agent": "KD-RAG/1.0"})
            resp.raise_for_status()
            from html.parser import HTMLParser

            class Extractor(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.parts = []
                    self._skip = 0
                def handle_starttag(self, tag, attrs):
                    if tag in ("script", "style"): self._skip += 1
                def handle_endtag(self, tag):
                    if tag in ("script", "style") and self._skip: self._skip -= 1
                def handle_data(self, data):
                    if not self._skip: self.parts.append(data)
            parser = Extractor()
            parser.feed(resp.text)
            text = " ".join(" ".join(parser.parts).split())
            return self.ingest(text, url, collection)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def query(self, question: str, collection: str = "default",
              top_k: int = 5, strategy: str = "hybrid") -> RAGResponse:
        """Query the knowledge base and generate an answer."""
        start = time.perf_counter()

        # Retrieve
        retrieval = self.retriever.retrieve(question, collection, top_k, strategy)

        if not retrieval.chunks:
            return RAGResponse(
                answer="I don't have any relevant information in the knowledge base to answer this question.",
                sources=[],
                collection=collection,
                retrieval_time_ms=retrieval.retrieval_time_ms,
                generation_time_ms=0,
                confidence=0.0
            )

        # Build context
        context_parts = []
        for i, chunk in enumerate(retrieval.chunks):
            context_parts.append(f"[Source {i+1}: {chunk.source}]\n{chunk.text}")
        context = "\n\n---\n\n".join(context_parts)

        # Generate answer
        gen_start = time.perf_counter()
        prompt = f"""Answer the question using only the provided context. If the context doesn't contain enough information, say so. Cite sources by their numbers.

Context:
{context}

Question: {question}

Answer:"""

        # Use non-streaming completion for RAG
        try:
            answer, _ = self.llm.complete([{"role": "user", "content": prompt}])
        except Exception as e:
            answer = f"Error generating answer: {e}"

        gen_time = (time.perf_counter() - gen_start) * 1000

        # Calculate confidence based on retrieval scores
        avg_score = np.mean(retrieval.scores) if retrieval.scores else 0.0
        confidence = min(1.0, avg_score * 1.5)  # Scale

        sources = [
            {
                "source": chunk.source,
                "chunk_id": chunk.id,
                "score": score,
                "snippet": chunk.text[:240],
            }
            for chunk, score in zip(retrieval.chunks, retrieval.scores)
        ]

        return RAGResponse(
            answer=answer.strip(),
            sources=sources,
            collection=collection,
            retrieval_time_ms=retrieval.retrieval_time_ms,
            generation_time_ms=gen_time,
            confidence=confidence
        )

    def list_collections(self) -> list[dict]:
        """List all collections with stats."""
        collections = self.store.list_collections()
        return [self.store.get_stats(c) for c in collections]

    def delete_collection(self, collection: str):
        """Delete a collection."""
        self.store.delete_collection(collection)

    def get_collection_stats(self, collection: str) -> dict:
        """Get stats for a collection."""
        return self.store.get_stats(collection)


# ─────────────────────────────────────────────────────────────────────────────
# Service Client (for remote knowledge-rag service)
# ─────────────────────────────────────────────────────────────────────────────


class RAGServiceClient:
    """Client for the knowledge-rag FastAPI service."""

    def __init__(self, base_url: str = RAG_SERVICE_URL):
        self.base_url = base_url
        self._session = requests.Session()
        self._session.trust_env = False

    def health(self) -> dict:
        resp = self._session.get(f"{self.base_url}/health", timeout=5)
        resp.raise_for_status()
        return resp.json()

    def ingest(self, collection: str, path: str | None = None,
               url: str | None = None, text: str | None = None) -> dict:
        payload = {"collection": collection}
        if path: payload["path"] = path
        if url: payload["url"] = url
        if text: payload["text"] = text
        resp = self._session.post(f"{self.base_url}/ingest", json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()

    def query(self, question: str, collection: str = "default", k: int = 4) -> dict:
        resp = self._session.post(f"{self.base_url}/query", json={
            "question": question, "collection": collection, "k": k
        }, timeout=180)
        resp.raise_for_status()
        return resp.json()

    def collections(self) -> dict:
        resp = self._session.get(f"{self.base_url}/collections", timeout=5)
        resp.raise_for_status()
        return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# Provider Declaration (for providers.registry)
# ─────────────────────────────────────────────────────────────────────────────


def _make(cfg: dict) -> RAGProvider:
    return RAGProvider(cfg)


PROVIDER = {
    "id": "rag",
    "kind": "rag",
    "label": "RAG Knowledge Base",
    "hint": "Local retrieval-augmented generation with hybrid search and reranking",
    "requires": ("numpy", "requests"),
    "install": "numpy requests rank-bm25 sentence-transformers",
    "needs": (
        Field("data_dir", "Data directory", kind="path", default=str(DATA_DIR)),
        Field("embed_base_url", "Embeddings endpoint", default=OPENAI_BASE_URL),
        Field("embed_model", "Embeddings model", default=EMBED_MODEL),
        Field("chat_model", "Chat model for generation", default="qwen3.5:2b"),
        Field("rerank_model", "Reranker model", default=RERANK_MODEL, advanced=True),
    ),
    "caps": {"retrieval": True, "generation": True, "reranking": True},
    "factory": _make,
}


def available() -> bool:
    from importlib.util import find_spec
    return all(find_spec(m) is not None for m in ("numpy", "requests"))