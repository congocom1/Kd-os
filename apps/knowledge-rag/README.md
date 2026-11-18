# knowledge-rag

Headless port of `awesome-llm-apps-main/rag_tutorials/autonomous_rag` (Streamlit +
agno + pgvector/Postgres RAG agent) as a local FastAPI service for JARVIS.

## What changed vs. the original

| Original | Here |
|---|---|
| Streamlit UI | FastAPI service on 127.0.0.1:7864, driven by `actions/knowledge_rag.py` |
| agno Agent / PDFUrlKnowledgeBase | plain `requests` to an OpenAI-compatible endpoint |
| pgvector + Postgres | sqlite (`data/chunks.db`) for chunk metadata + one `vectors.npy` per collection, cosine similarity in numpy |
| OpenAI API (paid) | local Ollama via `OPENAI_BASE_URL` (default `http://localhost:11434/v1`, key `ollama`) |
| DuckDuckGo fallback tool | not ported — JARVIS already has its own web-search action |
| GPT-4o-mini | `KNOWLEDGE_CHAT_MODEL` (default `qwen3.5:2b`) |

Chunking mirrors agno's `FixedSizeChunking` default used by the original
knowledge base: 5000 characters, 200 overlap, sentence-aware boundaries.
Retrieval keeps the original's `num_documents=3` as the default `k`.

## Embeddings / retrieval

Vectors come from the OpenAI-compatible embeddings endpoint
(`KNOWLEDGE_EMBED_MODEL`, default `qwen3-embedding:0.6b` on local Ollama).
If the endpoint is unreachable at ingest time, the collection is stored as a
numpy-only TF-IDF bag-of-words matrix instead (re-fit on each ingest), so the
service keeps working with zero external dependencies. The mode is recorded
per collection in `meta.json`.

## Endpoints

- `GET /health` — service status, backend availability, collections
- `POST /ingest` — `{path | url | text, collection?}` → chunk + embed + store
- `POST /query` — `{question, collection?, k?}` → `{answer, sources}`
- `GET /collections` — list collections and chunk counts

## Run

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python service.py --port 7864
```

The JARVIS action `actions/knowledge_rag.py` starts this automatically on
first use. Env: `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `KNOWLEDGE_EMBED_MODEL`,
`KNOWLEDGE_CHAT_MODEL`, `KNOWLEDGE_DATA_DIR`, `KNOWLEDGE_PORT`.
