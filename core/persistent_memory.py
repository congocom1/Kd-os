"""
core/persistent_memory.py — Enhanced Persistent Memory (KD Upgrade).

Extends the existing memory_manager with:
  • Vector embeddings for semantic search
  • Cross-session continuity
  • Memory consolidation and summarization
  • Automatic importance scoring
  • Zero-regression: gated by PERSISTENT_MEMORY flag, additive to existing memory

Optional dependencies: sentence-transformers, faiss-cpu, chromadb
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pickle
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np

from core.feature_flags import is_enabled
from core.awareness_engine import get_awareness_engine, EventType
from memory.memory_manager import load_memory, save_memory, update_memory, search_memory

logger = logging.getLogger("jarvis.persistent_memory")


# ── Vector Store Backend ──────────────────────────────────────────────────────

class VectorStore:
    """Abstract vector store for embeddings."""

    def add(self, ids: list[str], embeddings: np.ndarray, metadatas: list[dict]) -> None:
        raise NotImplementedError

    def search(self, query_embedding: np.ndarray, k: int = 5,
               filter_dict: dict | None = None) -> list[tuple[str, float, dict]]:
        raise NotImplementedError

    def delete(self, ids: list[str]) -> None:
        raise NotImplementedError

    def persist(self) -> None:
        raise NotImplementedError


class FaissVectorStore(VectorStore):
    """FAISS-based vector store (fast, local)."""

    def __init__(self, dim: int, path: Path):
        self.dim = dim
        self.path = path
        self.index = None
        self.id_map: list[str] = []
        self.metadata: list[dict] = []
        self._load_or_create()

    def _load_or_create(self) -> None:
        try:
            import faiss
            if self.path.exists():
                self.index = faiss.read_index(str(self.path))
                meta_path = self.path.with_suffix(".meta.pkl")
                if meta_path.exists():
                    with open(meta_path, "rb") as f:
                        data = pickle.load(f)
                        self.id_map = data["ids"]
                        self.metadata = data["metadatas"]
                logger.info(f"Loaded FAISS index with {self.index.ntotal} vectors")
            else:
                self.index = faiss.IndexFlatIP(self.dim)  # Inner product (cosine with normalized)
                logger.info("Created new FAISS index")
        except ImportError:
            raise RuntimeError("faiss-cpu not installed. Run: pip install faiss-cpu")

    def add(self, ids: list[str], embeddings: np.ndarray, metadatas: list[dict]) -> None:
        import faiss
        # Normalize for cosine similarity
        faiss.normalize_L2(embeddings)
        self.index.add(embeddings)
        self.id_map.extend(ids)
        self.metadata.extend(metadatas)

    def search(self, query_embedding: np.ndarray, k: int = 5,
               filter_dict: dict | None = None) -> list[tuple[str, float, dict]]:
        import faiss
        faiss.normalize_L2(query_embedding.reshape(1, -1))
        k = min(k, self.index.ntotal)
        if k == 0:
            return []
        scores, indices = self.index.search(query_embedding.reshape(1, -1), k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0 and idx < len(self.id_map):
                results.append((self.id_map[idx], float(score), self.metadata[idx]))
        return results

    def delete(self, ids: list[str]) -> None:
        # FAISS doesn't support deletion easily; rebuild
        import faiss
        keep_indices = [i for i, id_ in enumerate(self.id_map) if id_ not in ids]
        if len(keep_indices) == len(self.id_map):
            return
        new_index = faiss.IndexFlatIP(self.dim)
        new_ids = []
        new_meta = []
        for i in keep_indices:
            # Re-add (we'd need to store vectors; simplified here)
            pass
        # Full rebuild needed - simplified
        logger.warning("FAISS deletion requires rebuild - not implemented")

    def persist(self) -> None:
        import faiss
        faiss.write_index(self.index, str(self.path))
        meta_path = self.path.with_suffix(".meta.pkl")
        with open(meta_path, "wb") as f:
            pickle.dump({"ids": self.id_map, "metadatas": self.metadata}, f)


class ChromaVectorStore(VectorStore):
    """ChromaDB-based vector store (persistent, feature-rich)."""

    def __init__(self, path: Path, collection_name: str = "jarvis_memory"):
        self.path = path
        self.collection_name = collection_name
        self.client = None
        self.collection = None
        self._init_client()

    def _init_client(self) -> None:
        try:
            import chromadb
            self.client = chromadb.PersistentClient(path=str(self.path))
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"}
            )
            logger.info(f"ChromaDB collection '{self.collection_name}' ready with {self.collection.count()} items")
        except ImportError:
            raise RuntimeError("chromadb not installed. Run: pip install chromadb")

    def add(self, ids: list[str], embeddings: np.ndarray, metadatas: list[dict]) -> None:
        self.collection.add(
            ids=ids,
            embeddings=embeddings.tolist(),
            metadatas=metadatas,
        )

    def search(self, query_embedding: np.ndarray, k: int = 5,
               filter_dict: dict | None = None) -> list[tuple[str, float, dict]]:
        results = self.collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=k,
            where=filter_dict,
        )
        out = []
        if results["ids"] and results["ids"][0]:
            for id_, dist, meta in zip(results["ids"][0], results["distances"][0], results["metadatas"][0]):
                # Chroma returns distance; convert to similarity
                sim = 1.0 - dist
                out.append((id_, sim, meta))
        return out

    def delete(self, ids: list[str]) -> None:
        self.collection.delete(ids=ids)

    def persist(self) -> None:
        # ChromaDB persists automatically
        pass


class SimpleVectorStore(VectorStore):
    """Simple numpy-based vector store (fallback, no deps)."""

    def __init__(self, dim: int, path: Path):
        self.dim = dim
        self.path = path
        self.embeddings = np.zeros((0, dim), dtype=np.float32)
        self.id_map: list[str] = []
        self.metadata: list[dict] = []
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = np.load(self.path, allow_pickle=True)
                self.embeddings = data["embeddings"]
                self.id_map = data["ids"].tolist()
                self.metadata = data["metadatas"].tolist()
                logger.info(f"Loaded simple vector store with {len(self.id_map)} vectors")
            except Exception as e:
                logger.warning(f"Failed to load vector store: {e}")

    def add(self, ids: list[str], embeddings: np.ndarray, metadatas: list[dict]) -> None:
        self.embeddings = np.vstack([self.embeddings, embeddings])
        self.id_map.extend(ids)
        self.metadata.extend(metadatas)

    def search(self, query_embedding: np.ndarray, k: int = 5,
               filter_dict: dict | None = None) -> list[tuple[str, float, dict]]:
        if len(self.embeddings) == 0:
            return []
        # Cosine similarity
        query_norm = query_embedding / (np.linalg.norm(query_embedding) + 1e-8)
        emb_norm = self.embeddings / (np.linalg.norm(self.embeddings, axis=1, keepdims=True) + 1e-8)
        scores = emb_norm @ query_norm
        k = min(k, len(scores))
        top_indices = np.argpartition(scores, -k)[-k:]
        top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]
        results = []
        for idx in top_indices:
            if filter_dict:
                match = all(self.metadata[idx].get(k) == v for k, v in filter_dict.items())
                if not match:
                    continue
            results.append((self.id_map[idx], float(scores[idx]), self.metadata[idx]))
        return results

    def delete(self, ids: list[str]) -> None:
        keep = [i for i, id_ in enumerate(self.id_map) if id_ not in ids]
        self.embeddings = self.embeddings[keep]
        self.id_map = [self.id_map[i] for i in keep]
        self.metadata = [self.metadata[i] for i in keep]

    def persist(self) -> None:
        np.savez_compressed(self.path,
                           embeddings=self.embeddings,
                           ids=np.array(self.id_map),
                           metadatas=np.array(self.metadata, dtype=object))


# ── Memory Entry with Embedding ───────────────────────────────────────────────

@dataclass
class EnhancedMemoryEntry:
    """Enhanced memory entry with embedding and metadata."""
    id: str
    category: str
    key: str
    value: str
    embedding: np.ndarray | None = None
    importance: float = 0.5  # 0-1
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)
    source: str = "user"  # user, system, inferred
    consolidated: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "category": self.category,
            "key": self.key,
            "value": self.value,
            "embedding": self.embedding.tolist() if self.embedding is not None else None,
            "importance": self.importance,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed,
            "created_at": self.created_at,
            "tags": self.tags,
            "source": self.source,
            "consolidated": self.consolidated,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EnhancedMemoryEntry":
        embedding = data.get("embedding")
        if embedding is not None:
            embedding = np.array(embedding, dtype=np.float32)
        return cls(
            id=data["id"],
            category=data["category"],
            key=data["key"],
            value=data["value"],
            embedding=embedding,
            importance=data.get("importance", 0.5),
            access_count=data.get("access_count", 0),
            last_accessed=data.get("last_accessed", time.time()),
            created_at=data.get("created_at", time.time()),
            tags=data.get("tags", []),
            source=data.get("source", "user"),
            consolidated=data.get("consolidated", False),
        )


# ── Embedding Provider ────────────────────────────────────────────────────────

class EmbeddingProvider:
    """Generates embeddings for text.

    Two backends, in this order:

    1. A sentence-transformers model, but ONLY if it is already cached on
       this machine. The model is loaded with ``local_files_only=True`` so it
       can never be downloaded: the zero-regression protocol (§6) forbids
       automatic large-model downloads, and a memory subsystem must never pull
       ~90 MB off the network behind the user's back.
    2. A local lexical embedding (hashed bag-of-words), which needs no model,
       no network and no GPU.

    The lexical fallback is genuinely similarity-bearing: cosine similarity
    between two of its vectors reflects how much vocabulary they share. The
    previous fallback hashed the WHOLE string with md5, so two sentences
    about the same subject had completely unrelated vectors and semantic
    recall could only ever match identical text.
    """

    MODEL_NAME = "all-MiniLM-L6-v2"
    DIM = 384

    def __init__(self):
        self.model = None
        self.dim = self.DIM
        self._load_model()

    def _load_model(self) -> None:
        """Use a locally cached model if there is one; never download one."""
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            logger.debug("sentence-transformers not available - using local embedding")
            return
        try:
            # local_files_only=True is the whole point: no network, no
            # surprise download, no stall on a first run.
            self.model = SentenceTransformer(self.MODEL_NAME, local_files_only=True)
            try:
                self.dim = int(self.model.get_embedding_dimension())
            except Exception:
                self.dim = int(self.model.get_sentence_embedding_dimension())
            logger.info(f"Using cached embedding model: {self.dim} dimensions")
        except Exception as e:
            logger.info(
                f"No cached embedding model ({type(e).__name__}); "
                "using the local lexical embedding instead."
            )
            self.model = None

    def embed(self, text: str) -> np.ndarray:
        """Generate embedding for text."""
        if self.model:
            try:
                emb = self.model.encode(text, convert_to_numpy=True,
                                        normalize_embeddings=True)
                return emb.astype(np.float32)
            except Exception as e:
                logger.debug(f"Embedding model failed, using local embedding: {e}")
        return self._lexical_embedding(text)

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        """Generate embeddings for multiple texts."""
        if self.model:
            try:
                embs = self.model.encode(texts, convert_to_numpy=True,
                                          normalize_embeddings=True)
                return embs.astype(np.float32)
            except Exception:
                pass
        return np.array([self._lexical_embedding(t) for t in texts],
                        dtype=np.float32)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [w for w in re.split(r"[^\w]+", (text or "").lower())
                if len(w) > 1]

    def _lexical_embedding(self, text: str) -> np.ndarray:
        """A hashed bag-of-words embedding — local, deterministic, and useful.

        Each distinct word is hashed into a bucket, weighted by its term
        frequency, and the vector is L2-normalised. Cosine similarity then
        measures shared vocabulary, so "the user's cat is called Pixel"
        retrieves "Pixel the cat" even though the strings differ.
        """
        vec = np.zeros(self.dim, dtype=np.float32)
        tokens = self._tokenize(text)
        if not tokens:
            return vec
        counts: dict[str, int] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        for token, count in counts.items():
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dim
            # Signed hashing keeps unrelated words from all piling into the
            # same direction and inflating the similarity.
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[bucket] += sign * (1.0 + np.log(count))
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm
        return vec


# ── Persistent Memory Engine ──────────────────────────────────────────────────

class PersistentMemoryEngine:
    """
    Enhanced persistent memory with vector search and cross-session continuity.

    Features:
    - Semantic search via embeddings
    - Automatic importance scoring
    - Memory consolidation (summarization)
    - Cross-session continuity
    - Integration with awareness engine
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._embedding_provider = EmbeddingProvider()
        self._vector_store: VectorStore | None = None
        self._entries: dict[str, EnhancedMemoryEntry] = {}
        self._initialized = False
        self._awareness = None
        self._event_token: int | None = None
        self._consolidation_thread: threading.Thread | None = None
        self._running = False

        # Storage paths
        base = Path(__file__).resolve().parent.parent
        self._memory_dir = base / "memory" / "enhanced"
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        self._vector_path = self._memory_dir / "vectors"
        self._entries_path = self._memory_dir / "entries.json"

    def initialize(self) -> bool:
        """Initialize the enhanced memory engine."""
        if self._initialized:
            return True
        if not is_enabled("PERSISTENT_MEMORY"):
            logger.info("Persistent memory not initialized: flag is off")
            return False

        try:
            # Initialize vector store (try FAISS, then Chroma, then simple)
            self._init_vector_store()
            # Load existing entries
            self._load_entries()
            # Connect to awareness engine
            self._connect_awareness()
            # Start consolidation thread
            self._start_consolidation()
            self._initialized = True
            logger.info(f"Persistent memory engine initialized with {len(self._entries)} entries")
            return True
        except Exception as e:
            logger.warning(f"Persistent memory initialization failed: {e}")
            return False

    def _init_vector_store(self) -> None:
        """Initialize the best available vector store."""
        dim = self._embedding_provider.dim

        # Try FAISS first
        try:
            self._vector_store = FaissVectorStore(dim, self._vector_path.with_suffix(".faiss"))
            logger.info("Using FAISS vector store")
            return
        except Exception:
            pass

        # Try ChromaDB
        try:
            self._vector_store = ChromaVectorStore(self._memory_dir / "chroma")
            logger.info("Using ChromaDB vector store")
            return
        except Exception:
            pass

        # Fallback to simple store
        self._vector_store = SimpleVectorStore(dim, self._vector_path.with_suffix(".npz"))
        logger.info("Using simple numpy vector store")

    def _connect_awareness(self) -> None:
        """Connect to awareness engine for event-driven updates."""
        if not is_enabled("REALTIME_AWARENESS"):
            return
        try:
            self._awareness = get_awareness_engine()
            if not self._awareness._started:
                self._awareness.start()
            # Watch memory-stored events so an entry written by another path
            # still gets an embedding.
            self._event_token = self._awareness.register_pattern(
                EventType.MEMORY_STORED,
                self._on_memory_stored
            )
        except Exception as e:
            logger.warning(f"Could not connect to awareness engine: {e}")

    def _on_memory_stored(self, events: list) -> None:
        """Handle memory stored events - create embeddings."""
        for ev in events:
            # The event payload should contain the memory entry
            payload = ev.payload
            entry_id = payload.get("entry_id")
            if entry_id and entry_id in self._entries:
                entry = self._entries[entry_id]
                if entry.embedding is None:
                    self._generate_embedding(entry)

    def _start_consolidation(self) -> None:
        """Start background consolidation thread."""
        self._running = True
        self._consolidation_thread = threading.Thread(
            target=self._consolidation_loop, daemon=True, name="MemoryConsolidation"
        )
        self._consolidation_thread.start()

    def _consolidation_loop(self) -> None:
        """Periodically consolidate memories."""
        while self._running:
            time.sleep(3600)  # Every hour
            if not self._running:
                break
            try:
                self.consolidate()
            except Exception as e:
                logger.warning(f"Consolidation error: {e}")

    def _generate_embedding(self, entry: EnhancedMemoryEntry) -> None:
        """Generate and store embedding for an entry."""
        text = f"{entry.category}: {entry.key} - {entry.value}"
        embedding = self._embedding_provider.embed(text)
        entry.embedding = embedding

        # Add to vector store
        if self._vector_store:
            self._vector_store.add([entry.id], embedding.reshape(1, -1), [entry.to_dict()])

    def _load_entries(self) -> None:
        """Load enhanced entries from disk."""
        if not self._entries_path.exists():
            return
        try:
            data = json.loads(self._entries_path.read_text())
            for entry_data in data.get("entries", []):
                entry = EnhancedMemoryEntry.from_dict(entry_data)
                self._entries[entry.id] = entry
            logger.info(f"Loaded {len(self._entries)} enhanced memory entries")
        except Exception as e:
            logger.warning(f"Failed to load enhanced entries: {e}")

    def _save_entries(self) -> None:
        """Save enhanced entries to disk."""
        try:
            data = {
                "entries": [e.to_dict() for e in self._entries.values()],
                "saved_at": time.time(),
            }
            self._entries_path.write_text(json.dumps(data, indent=2))
            if self._vector_store:
                self._vector_store.persist()
        except Exception as e:
            logger.warning(f"Failed to save enhanced entries: {e}")

    # ── Core Operations ──────────────────────────────────────────────────────

    def store(self, category: str, key: str, value: str,
              importance: float = 0.5, tags: list[str] = None,
              source: str = "user") -> str:
        """
        Store a memory entry with automatic embedding generation.

        Returns the entry ID.
        """
        with self._lock:
            # Create entry
            entry_id = hashlib.sha256(f"{category}:{key}:{time.time()}".encode()).hexdigest()[:16]
            entry = EnhancedMemoryEntry(
                id=entry_id,
                category=category,
                key=key,
                value=value,
                importance=importance,
                tags=tags or [],
                source=source,
            )

            # Generate embedding
            self._generate_embedding(entry)

            # Store
            self._entries[entry_id] = entry
            self._save_entries()

            # Also store in legacy memory for compatibility
            update_memory({category: {key: {"value": value}}})

            # Publish event
            if self._awareness:
                self._awareness.publish(
                    EventType.MEMORY_STORED,
                    {"entry_id": entry_id, "category": category, "key": key}
                )

            return entry_id

    def recall(self, query: str, k: int = 5, category: str | None = None) -> list[dict]:
        """
        Semantic recall - find relevant memories by meaning.

        Returns list of {entry, score, matched_text} dicts.
        """
        with self._lock:
            if not self._vector_store or not self._entries:
                return []

            # Generate query embedding
            query_emb = self._embedding_provider.embed(query)

            # Search vector store
            filter_dict = {"category": category} if category else None
            results = self._vector_store.search(query_emb, k=k, filter_dict=filter_dict)

            # Format results
            output = []
            for entry_id, score, meta in results:
                entry = self._entries.get(entry_id)
                if entry:
                    # Update access stats
                    entry.access_count += 1
                    entry.last_accessed = time.time()
                    output.append({
                        "entry": entry.to_dict(),
                        "score": score,
                        "matched_text": f"{entry.category}: {entry.key} - {entry.value[:100]}",
                    })

            self._save_entries()
            return output

    def get_entry(self, entry_id: str) -> EnhancedMemoryEntry | None:
        """Get entry by ID."""
        with self._lock:
            return self._entries.get(entry_id)

    def update_entry(self, entry_id: str, **kwargs) -> bool:
        """Update an entry's fields."""
        with self._lock:
            entry = self._entries.get(entry_id)
            if not entry:
                return False

            # Update fields
            for key, value in kwargs.items():
                if hasattr(entry, key):
                    setattr(entry, key, value)

            # Regenerate embedding if value changed
            if "value" in kwargs or "key" in kwargs or "category" in kwargs:
                self._generate_embedding(entry)

            self._save_entries()
            return True

    def delete_entry(self, entry_id: str) -> bool:
        """Delete an entry."""
        with self._lock:
            if entry_id not in self._entries:
                return False
            del self._entries[entry_id]
            if self._vector_store:
                self._vector_store.delete([entry_id])
            self._save_entries()
            return True

    def list_entries(self, category: str | None = None,
                     limit: int = 100, offset: int = 0) -> list[EnhancedMemoryEntry]:
        """List entries with optional category filter."""
        with self._lock:
            entries = list(self._entries.values())
            if category:
                entries = [e for e in entries if e.category == category]
            # Sort by importance * recency
            entries.sort(key=lambda e: e.importance * (1.0 / (1.0 + time.time() - e.last_accessed)), reverse=True)
            return entries[offset:offset + limit]

    # ── Importance Scoring ──────────────────────────────────────────────────

    def compute_importance(self, entry: EnhancedMemoryEntry) -> float:
        """
        Compute importance score based on:
        - Access frequency
        - Recency
        - Source (user > system > inferred)
        - Explicit tags
        """
        # Base score from explicit importance
        score = entry.importance

        # Boost from access count (logarithmic)
        score += 0.1 * np.log1p(entry.access_count)

        # Recency decay (half-life ~ 30 days)
        days_old = (time.time() - entry.last_accessed) / 86400
        recency_factor = np.exp(-days_old / 30)
        score += 0.2 * recency_factor

        # Source boost
        source_boost = {"user": 0.3, "system": 0.1, "inferred": 0.0}
        score += source_boost.get(entry.source, 0)

        # Tag boost
        if "important" in entry.tags:
            score += 0.2
        if "core" in entry.tags:
            score += 0.3

        return min(1.0, score)

    def refresh_importance(self) -> None:
        """Recompute importance for all entries."""
        with self._lock:
            for entry in self._entries.values():
                entry.importance = self.compute_importance(entry)
            self._save_entries()

    # ── Consolidation ────────────────────────────────────────────────────────

    def consolidate(self, max_entries: int = 1000) -> int:
        """
        Consolidate memories: summarize old/low-importance entries.

        Returns number of entries consolidated.
        """
        with self._lock:
            # Find candidates for consolidation
            candidates = [
                e for e in self._entries.values()
                if not e.consolidated
                and e.importance < 0.3
                and e.access_count < 2
                and (time.time() - e.created_at) > 86400 * 7  # Older than 7 days
            ]

            if not candidates:
                return 0

            # Sort by importance (lowest first)
            candidates.sort(key=lambda e: e.importance)

            consolidated_count = 0
            for entry in candidates[:max_entries]:
                # Create summary entry
                summary = self._create_summary(entry)
                if summary:
                    entry.consolidated = True
                    entry.tags.append("consolidated")
                    consolidated_count += 1

            if consolidated_count > 0:
                self._save_entries()
                logger.info(f"Consolidated {consolidated_count} memory entries")

            return consolidated_count

    def _create_summary(self, entry: EnhancedMemoryEntry) -> str | None:
        """Create a summary for an entry (placeholder for LLM summarization)."""
        # In a full implementation, this would call an LLM
        # For now, just create a brief summary
        return f"[Consolidated] {entry.category}/{entry.key}: {entry.value[:200]}"

    # ── Cross-Session Continuity ────────────────────────────────────────────

    def get_session_context(self) -> dict:
        """Get context for session initialization (recent, important memories)."""
        with self._lock:
            # Get recent high-importance entries
            entries = list(self._entries.values())
            entries.sort(key=lambda e: e.importance * (1.0 / (1.0 + time.time() - e.last_accessed)), reverse=True)

            top_entries = entries[:20]
            return {
                "recent_important": [e.to_dict() for e in top_entries],
                "total_entries": len(self._entries),
                "categories": list(set(e.category for e in entries)),
                "timestamp": time.time(),
            }

    def export_for_backup(self) -> dict:
        """Export all memory for backup."""
        with self._lock:
            return {
                "entries": [e.to_dict() for e in self._entries.values()],
                "exported_at": time.time(),
                "version": "1.0",
            }

    def import_from_backup(self, data: dict) -> int:
        """Import memory from backup."""
        with self._lock:
            count = 0
            for entry_data in data.get("entries", []):
                entry = EnhancedMemoryEntry.from_dict(entry_data)
                if entry.id not in self._entries:
                    self._entries[entry.id] = entry
                    if entry.embedding is not None and self._vector_store:
                        self._vector_store.add(
                            [entry.id], entry.embedding.reshape(1, -1), [entry.to_dict()]
                        )
                    count += 1
            self._save_entries()
            return count

    # ── Shutdown ─────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """Clean shutdown."""
        self._running = False
        if self._consolidation_thread:
            self._consolidation_thread.join(timeout=5.0)
        self._save_entries()
        self._initialized = False


# ── Singleton ────────────────────────────────────────────────────────────────

_engine: PersistentMemoryEngine | None = None


def get_persistent_memory() -> PersistentMemoryEngine | None:
    """Get or create the global persistent memory engine."""
    global _engine
    if not is_enabled("PERSISTENT_MEMORY"):
        return None
    if _engine is None:
        _engine = PersistentMemoryEngine()
        _engine.initialize()
    return _engine


# ── Convenience Functions (compatible with existing memory_manager API) ──────

def enhanced_store(category: str, key: str, value: str, **kwargs) -> str:
    """Store using enhanced memory (falls back to legacy if disabled)."""
    engine = get_persistent_memory()
    if engine:
        return engine.store(category, key, value, **kwargs)
    # Fallback to legacy
    update_memory({category: {key: {"value": value}}})
    return "legacy"


def enhanced_recall(query: str, k: int = 5, category: str | None = None) -> list[dict]:
    """Recall using enhanced memory (falls back to legacy if disabled)."""
    engine = get_persistent_memory()
    if engine:
        return engine.recall(query, k, category)
    # Fallback to legacy. memory_manager.search_memory(query, limit) returns a
    # formatted STRING (not a list) and takes no category argument — the old
    # call passed both and raised TypeError on every fallback recall.
    text = search_memory(query, limit=k)
    return [{"entry": text, "score": 1.0, "matched_text": text}]