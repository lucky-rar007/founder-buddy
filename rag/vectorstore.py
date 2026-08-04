"""
ChromaDB Vector Store Wrapper.

Provides vector storage, incremental updates, and semantic search over thread chunks.
"""

from __future__ import annotations

import os
import json
import logging
from pathlib import Path

import chromadb

from typing import Any

logger = logging.getLogger(__name__)

_DB_DIR = Path(__file__).resolve().parent.parent / "data" / "chroma_db"


class ChromaVectorStore:
    """
    Manages collection storage, updates, and cosine metadata queries in ChromaDB.
    """

    def __init__(self) -> None:
        os.makedirs(_DB_DIR, exist_ok=True)
        # Use PersistentClient to save vectors to data/chroma_db
        self.client = chromadb.PersistentClient(path=str(_DB_DIR))
        self.collection = self.client.get_or_create_collection(
            name="org_threads",
            metadata={"hnsw:space": "cosine"}
        )

    def add_documents(self, chunks: list[dict[str, Any]], embeddings: list[list[float]]) -> bool:
        """
        Add text chunks and their matching embeddings to the vector store.
        `chunks` list should have entries with doc_id, chunk_text, and metadata_json.
        """
        if not chunks or not embeddings:
            return False

        ids = []
        documents = []
        metadatas = []

        for c in chunks:
            ids.append(c["doc_id"])
            documents.append(c["chunk_text"])
            
            # ChromaDB requires a flat metadata dict (keys are string/int/float/bool)
            meta_str = c.get("metadata_json", "{}")
            try:
                meta = json.loads(meta_str) if isinstance(meta_str, str) else (meta_str or {})
            except Exception:
                meta = {}
            
            clean_meta = {}
            if isinstance(meta, dict):
                for k, v in meta.items():
                    if isinstance(v, (str, int, float, bool)):
                        clean_meta[k] = v
                    elif v is None:
                        clean_meta[k] = ""
                    else:
                        clean_meta[k] = str(v)
            metadatas.append(clean_meta)

        try:
            self.collection.upsert(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas
            )
            logger.info(f"[ChromaVectorStore] Successfully upserted {len(chunks)} documents to collection.")
            return True
        except Exception as e:
            logger.error(f"[ChromaVectorStore] Failed to upsert documents: {e}")
            return False

    def search(self, query_embedding: list[float], n_results: int = 5,
               metadata_filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """
        Run cosine similarity query against the thread collection.
        `metadata_filters` can specify ChromaDB queries (e.g. {"source": "outlook"}).
        """
        try:
            # query params: query_embeddings, n_results, where (metadata filters)
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=metadata_filters
            )

            # Restructure output to list of matches
            matches = []
            if not results or "ids" not in results or not results["ids"]:
                return []

            ids = results["ids"][0] if results["ids"] else []
            documents = results["documents"][0] if results.get("documents") else []
            metadatas = results["metadatas"][0] if results.get("metadatas") else []
            distances = results["distances"][0] if results.get("distances") else []

            for i in range(len(ids)):
                doc_text = documents[i] if i < len(documents) else ""
                doc_meta = metadatas[i] if i < len(metadatas) else {}
                dist = distances[i] if i < len(distances) else 0.0
                matches.append({
                    "doc_id": ids[i],
                    "text": doc_text,
                    "metadata": doc_meta,
                    "distance": dist,
                    "relevance_score": round(max(0.0, 1.0 - dist), 3)
                })

            return matches

        except Exception as e:
            logger.error(f"[ChromaVectorStore] Vector search failed: {e}")
            return []

    def get_count(self) -> int:
        """Get the total number of items indexed in the collection."""
        try:
            return self.collection.count()
        except Exception:
            return 0

    def reset_collection(self) -> bool:
        """Delete and recreate the collection (wipe index)."""
        try:
            self.client.delete_collection("org_threads")
            self.collection = self.client.get_or_create_collection(
                name="org_threads",
                metadata={"hnsw:space": "cosine"}
            )
            logging.info("[ChromaVectorStore] Vector index cleared.")
            return True
        except Exception as e:
            logger.error(f"[ChromaVectorStore] Failed to clear collection: {e}")
            return False
