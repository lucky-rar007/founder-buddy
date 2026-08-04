"""
Unit tests for RAG Chunking, Embeddings, and ChromaVectorStore operations.
"""

import pytest
import random
from rag.chunker import ThreadChunker
from rag.vectorstore import ChromaVectorStore
from rag.pipeline import RAGPipeline
import rag.embedder


def mock_embed_text(self, text):
    random.seed(hash(text))
    vec = [random.uniform(-0.1, 0.1) for _ in range(768)]
    norm = sum(x**2 for x in vec)**0.5
    return [x / norm for x in vec]

def mock_embed_batch(self, texts):
    return [mock_embed_text(self, t) for t in texts]


@pytest.fixture(autouse=True)
def patch_embedder(monkeypatch):
    monkeypatch.setattr(rag.embedder.GeminiEmbedder, "embed_text", mock_embed_text)
    monkeypatch.setattr(rag.embedder.GeminiEmbedder, "embed_batch", mock_embed_batch)


def test_thread_chunker():
    chunker = ThreadChunker(chunk_size=100, overlap=20)
    mock_thread = {
        "thread_id": "th_test_001",
        "subject": "Deployment Failure",
        "thread_date": "2026-07-19",
        "source": "teams",
        "team_name": "DevOps",
        "channel_name": "Alerts",
        "participants": "Alice, Bob",
        "raw_text": "Error 500 on server cluster 3. High CPU usage detected on web worker node."
    }

    chunks = chunker.chunk_thread(mock_thread)
    assert len(chunks) >= 1
    c = chunks[0]
    assert c["thread_id"] == "th_test_001"
    assert "=== CONVERSATION CONTEXT ===" in c["chunk_text"]
    assert "Subject: Deployment Failure" in c["chunk_text"]


def test_chroma_vector_store():
    store = ChromaVectorStore()
    
    mock_chunks = [
        {
            "doc_id": "doc_test_101",
            "thread_id": "th_test_101",
            "chunk_index": 0,
            "chunk_text": "=== CONVERSATION CONTEXT ===\nSubject: Database Latency\n\nSlow query logs on Postgres master.",
            "metadata_json": '{"thread_id": "th_test_101", "subject": "Database Latency", "source": "teams"}'
        }
    ]

    mock_embeddings = [mock_embed_text(None, mock_chunks[0]["chunk_text"])]

    # Test upsert
    success = store.add_documents(mock_chunks, mock_embeddings)
    assert success is True

    # Test similarity search
    query_vec = mock_embed_text(None, "Database query speed")
    matches = store.search(query_vec, n_results=1)

    assert len(matches) >= 1
    assert isinstance(matches[0]["doc_id"], str)


def test_thread_indexer(monkeypatch):
    from rag.indexer import ThreadIndexer
    from shared.database import get_db, init_db

    init_db()

    with get_db() as conn:
        conn.execute("DELETE FROM rag_documents WHERE thread_id = 'th_indexer_001'")
        conn.execute(
            """INSERT OR REPLACE INTO threads
               (thread_id, source, source_id, subject, participants, message_count,
                first_message_at, last_message_at, raw_text, team_name, channel_name, thread_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("th_indexer_001", "teams", "src_001", "Memory Leak Issue", "Dev1, Dev2", 2,
             "2026-07-20T10:00:00", "2026-07-20T10:05:00", "High memory usage observed on node 4.", "Engineering", "General", "2026-07-20")
        )

    indexer = ThreadIndexer(api_key="mock_key")
    count = indexer.index_pending_threads(clear_first=False)
    assert count >= 1

    with get_db() as conn:
        row = conn.execute("SELECT doc_id, thread_id FROM rag_documents WHERE thread_id = 'th_indexer_001'").fetchone()
        assert row is not None
        assert row["thread_id"] == "th_indexer_001"


def test_fts_search_sanitization():
    from shared.database import fts_search, get_db, init_db

    init_db()

    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO threads
               (thread_id, source, source_id, subject, participants, message_count,
                first_message_at, last_message_at, raw_text, team_name, channel_name, thread_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("th_fts_001", "teams", "src_002", "Production Escalation", "Ops1", 1,
             "2026-07-21T10:00:00", "2026-07-21T10:00:00", "Database connection pool exhausted during peak load.", "Ops", "Alerts", "2026-07-21")
        )

    results = fts_search('Database: connection "pool"* AND OR NOT', limit=5)
    assert len(results) >= 1
    assert any(r["thread_id"] == "th_fts_001" for r in results)
