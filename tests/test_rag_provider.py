"""Tests for RAG provider - unit tests only (no model downloads)."""
import sys
import tempfile
from pathlib import Path

import pytest
import numpy as np

from providers import rag
from providers.rag import (
    VectorStore, Chunk, chunk_text_fixed, chunk_text_semantic,
    EmbeddingProvider, RetrievalEngine, Reranker, RAGProvider, RAGServiceClient,
)


def test_chunk_text_fixed():
    """Test fixed-size chunking."""
    text = "Sentence one. Sentence two. Sentence three. " * 20
    chunks = chunk_text_fixed(text, chunk_size=200, overlap=50)

    assert len(chunks) > 0
    for chunk in chunks:
        assert len(chunk) <= 250  # Some flexibility for sentence boundaries


def test_chunk_text_semantic_fallback(monkeypatch):
    """Test semantic chunking falls back to fixed when model unavailable."""
    text = "First sentence. Second sentence. Third sentence. " * 10
    # Do not load models even if the optional package is installed.
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    chunks = chunk_text_semantic(text, max_chunk_size=200)
    assert len(chunks) > 0


def test_vector_store_basic():
    """Test VectorStore CRUD operations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = VectorStore(Path(tmpdir))

        # Add chunks
        chunks = [
            Chunk(id=0, text="Test chunk 1", source="test.txt", collection="test"),
            Chunk(id=0, text="Test chunk 2", source="test.txt", collection="test"),
        ]
        ids = store.add_chunks("test", chunks)
        assert len(ids) == 2

        # Get chunks
        retrieved = store.get_chunks("test")
        assert len(retrieved) == 2
        assert retrieved[0].text == "Test chunk 1"
        assert retrieved[1].text == "Test chunk 2"

        # Vectors
        vectors = np.random.rand(2, 384).astype(np.float32)
        store.save_vectors("test", vectors)
        loaded = store.load_vectors("test")
        assert loaded is not None
        assert loaded.shape == (2, 384)

        # Meta
        store.save_meta("test", {"mode": "dense", "custom": "value"})
        meta = store.load_meta("test")
        assert meta["mode"] == "dense"
        assert meta["custom"] == "value"

        # Collections
        collections = store.list_collections()
        assert "test" in collections

        # Stats
        stats = store.get_stats("test")
        assert stats["chunk_count"] == 2
        assert stats["has_vectors"] is True

        # Delete
        store.delete_collection("test")
        collections = store.list_collections()
        assert "test" not in collections


def test_vector_store_multiple_collections():
    """Test multiple collections isolation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = VectorStore(Path(tmpdir))

        store.add_chunks("col1", [Chunk(id=0, text="c1", source="s1", collection="col1")])
        store.add_chunks("col2", [Chunk(id=0, text="c2", source="s2", collection="col2")])

        assert len(store.get_chunks("col1")) == 1
        assert len(store.get_chunks("col2")) == 1


def test_embedding_provider_init():
    """Test EmbeddingProvider initialization."""
    embedder = EmbeddingProvider()
    assert embedder.base_url is not None
    assert embedder.model is not None


def test_retrieval_engine_basic():
    """Test RetrievalEngine with mocked embedder."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = VectorStore(Path(tmpdir))

        # Create mock embedder
        class MockEmbedder:
            def embed(self, texts):
                # Return deterministic embeddings based on text hash
                return np.array([[hash(t) % 1000 / 1000.0] * 384 for t in texts], dtype=np.float32)

            def embed_one(self, text):
                return self.embed([text])[0]

        embedder = MockEmbedder()

        # Add test data
        chunks = [
            Chunk(id=0, text="The quick brown fox jumps", source="doc1", collection="test"),
            Chunk(id=0, text="A fast fox leaps high", source="doc2", collection="test"),
            Chunk(id=0, text="Cats sleep all day", source="doc3", collection="test"),
        ]
        ids = store.add_chunks("test", chunks)
        for c, cid in zip(chunks, ids):
            c.id = cid

        embeddings = embedder.embed([c.text for c in chunks])
        for c, e in zip(chunks, embeddings):
            c.embedding = e
        store.save_vectors("test", embeddings)

        # Test retrieval
        retriever = RetrievalEngine(store, embedder)
        result = retriever.retrieve("fox jumping", "test", top_k=2)

        assert len(result.chunks) == 2
        assert result.query == "fox jumping"
        assert result.collection == "test"
        assert result.retrieval_time_ms > 0
        # Fox-related chunks should rank higher
        assert any("fox" in c.text.lower() for c in result.chunks)


def test_retrieval_engine_empty():
    """Test retrieval on empty collection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = VectorStore(Path(tmpdir))

        class MockEmbedder:
            def embed(self, texts):
                return np.random.rand(len(texts), 384).astype(np.float32)
            def embed_one(self, text):
                return self.embed([text])[0]

        retriever = RetrievalEngine(store, MockEmbedder())
        result = retriever.retrieve("any query", "empty_collection", top_k=5)

        assert len(result.chunks) == 0
        assert result.scores == []


def test_reranker_init():
    """Test Reranker initialization (no model load)."""
    reranker = Reranker()
    assert reranker.model_name is not None
    assert reranker._model is None  # Lazy load


def test_rag_provider_init():
    """Test RAGProvider initialization."""
    with tempfile.TemporaryDirectory() as tmpdir:
        provider = RAGProvider({"data_dir": tmpdir})
        assert provider.store is not None
        assert provider.embedder is not None
        assert provider.retriever is not None
        assert provider.llm is not None


@pytest.fixture
def offline_provider(tmp_path, monkeypatch):
    """Keep ingest/query tests independent of model servers and downloads."""
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    provider = RAGProvider({"data_dir": str(tmp_path)})
    monkeypatch.setattr(provider.embedder, "embed", lambda texts: np.ones((len(texts), 4)))
    provider.retriever.reranker = None
    return provider


def test_rag_provider_ingest_and_query_unit(offline_provider, monkeypatch):
    provider = offline_provider
    monkeypatch.setattr(provider.llm, "complete", lambda _: ("Mocked answer", []))
    result = provider.ingest("Python is a programming language.", "test.txt", "test")
    assert result["status"] == "ok"
    assert result["chunks_added"] == 1

    response = provider.query("What is Python?", "test", top_k=2)
    assert response.answer == "Mocked answer"
    assert [source["source"] for source in response.sources] == ["test.txt"]
    assert response.collection == "test"


def test_ingest_copies_metadata_per_chunk(offline_provider, monkeypatch):
    provider = offline_provider
    monkeypatch.setattr(rag, "chunk_text_fixed", lambda text: ["first", "second"])
    metadata = {"title": "Example"}
    result = provider.ingest("first second", "doc", chunking="fixed", metadata=metadata)
    assert result["total_chunks"] == 2
    assert metadata == {"title": "Example"}
    chunks = provider.store.get_chunks("default")
    assert [chunk.metadata for chunk in chunks] == [
        {"title": "Example", "chunk_index": 0, "total_chunks": 2},
        {"title": "Example", "chunk_index": 1, "total_chunks": 2},
    ]


@pytest.mark.parametrize("shape", [(0, 4), (1, 3), (4,)])
def test_invalid_embedding_does_not_change_collection(offline_provider, monkeypatch, shape):
    provider = offline_provider
    assert provider.ingest("first", "doc", chunking="fixed")["status"] == "ok"
    before = provider.store.load_vectors("default").copy()
    monkeypatch.setattr(provider.embedder, "embed", lambda texts: np.zeros(shape))
    assert provider.ingest("second", "doc", chunking="fixed")["status"] == "error"
    assert provider.store.count_chunks("default") == 1
    np.testing.assert_array_equal(provider.store.load_vectors("default"), before)


def test_rag_service_client():
    """Test RAGServiceClient initialization."""
    client = RAGServiceClient("http://127.0.0.1:7864")
    assert client.base_url == "http://127.0.0.1:7864"


def test_rag_provider_list_collections(offline_provider):
    offline_provider.ingest("Text for col1", "s1.txt", "col1")
    offline_provider.ingest("Text for col2", "s2.txt", "col2")
    assert {c["collection"] for c in offline_provider.list_collections()} == {"col1", "col2"}


def test_rag_provider_delete_collection(offline_provider):
    offline_provider.ingest("Text to delete", "s1.txt", "to_delete")
    assert len(offline_provider.list_collections()) == 1
    offline_provider.delete_collection("to_delete")
    assert offline_provider.list_collections() == []


def test_rag_provider_stats(offline_provider):
    offline_provider.ingest("Some text content here.", "source.txt", "stats_test")
    stats = offline_provider.get_collection_stats("stats_test")
    assert stats["collection"] == "stats_test"
    assert stats["chunk_count"] == 1
    assert stats["has_vectors"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
