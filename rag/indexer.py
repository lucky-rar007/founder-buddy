"""
Batch Thread Vectorization Orchestrator.

Orchestrates fetching threads from SQLite, chunking, embedding generation,
and indexing into ChromaDB and rag_documents tracking tables.
"""

from __future__ import annotations

import logging
import json
from shared.database import get_db, get_config
from dashboard.db import get_threads
from rag.chunker import ThreadChunker
from rag.embedder import GeminiEmbedder
from rag.vectorstore import ChromaVectorStore

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")


class ThreadIndexer:
    """
    Coordinates batch indexing of communication threads.
    """

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or get_config("gemini_api_key")
        self.chunker = ThreadChunker()
        self.embedder = GeminiEmbedder(api_key=self.api_key)
        self.vector_store = ChromaVectorStore()

    def get_indexed_thread_ids(self) -> set[str]:
        """Fetch set of all thread_ids already indexed in rag_documents."""
        with get_db() as conn:
            rows = conn.execute("SELECT DISTINCT thread_id FROM rag_documents").fetchall()
            return {r[0] for r in rows}

    def index_pending_threads(self, clear_first: bool = False) -> int:
        """
        Scan SQLite threads table, chunk and embed any new threads,
        and index them incrementally in ChromaDB.
        """
        if not self.api_key:
            logging.error("[Indexer] Cannot run indexing: Gemini API Key is missing.")
            return 0

        if clear_first:
            logging.info("[Indexer] Wiping existing vector index...")
            self.vector_store.reset_collection()
            with get_db() as conn:
                conn.execute("DELETE FROM rag_documents")
                conn.commit()

        # Load all threads from SQLite
        all_threads = get_threads()
        if not all_threads:
            logging.info("[Indexer] No threads found in database to index.")
            return 0

        indexed_ids = self.get_indexed_thread_ids()
        pending_threads = [t for t in all_threads if t["thread_id"] not in indexed_ids]

        if not pending_threads:
            logging.info("[Indexer] All threads are already indexed. Index is up to date.")
            return 0

        logging.info(f"[Indexer] Found {len(pending_threads)} new threads to index. Processing in streaming batches...")
        
        thread_batch_size = 50
        total_chunks_indexed = 0

        for t_idx in range(0, len(pending_threads), thread_batch_size):
            thread_batch = pending_threads[t_idx:t_idx + thread_batch_size]
            
            # Chunk threads in current batch
            batch_chunks = []
            for t in thread_batch:
                chunks = self.chunker.chunk_thread(t)
                batch_chunks.extend(chunks)

            if not batch_chunks:
                continue

            # Embed chunks in API sub-batches of 100
            embeddings = []
            embed_batch_size = 100
            for i in range(0, len(batch_chunks), embed_batch_size):
                sub_batch = batch_chunks[i:i + embed_batch_size]
                texts = [c["chunk_text"] for c in sub_batch]
                try:
                    batch_embeddings = self.embedder.embed_batch(texts)
                    embeddings.extend(batch_embeddings)
                except Exception as e:
                    logging.error(f"[Indexer] Failed to generate embeddings for sub-batch: {e}")
                    return total_chunks_indexed

            # Save batch to ChromaDB vector store
            success = self.vector_store.add_documents(batch_chunks, embeddings)
            if not success:
                logging.error("[Indexer] ChromaDB storage operation failed for thread batch.")
                return total_chunks_indexed

            # Record indexed document metadata in SQLite rag_documents
            with get_db() as conn:
                for c in batch_chunks:
                    conn.execute(
                        """INSERT OR REPLACE INTO rag_documents
                           (doc_id, thread_id, chunk_index, chunk_text, metadata_json)
                           VALUES (?, ?, ?, ?, ?)""",
                        (
                            c["doc_id"], c["thread_id"], c["chunk_index"],
                            c["chunk_text"], c["metadata_json"]
                        )
                    )
                conn.commit()

            total_chunks_indexed += len(batch_chunks)
            logging.info(f"[Indexer] Indexed batch {t_idx // thread_batch_size + 1}: {len(thread_batch)} threads ({len(batch_chunks)} chunks).")

        logging.info(f"[Indexer] Incremental indexing complete. Indexed {len(pending_threads)} threads ({total_chunks_indexed} chunks).")
        return len(pending_threads)
