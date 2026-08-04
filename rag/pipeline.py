"""
RAG Query Pipeline — Self-Querying & Hybrid Search.

Implements Self-Querying Query Decomposition (parsing user intent into FTS5 keywords
and dense semantic vectors), executes hybrid search (SQLite FTS5 + ChromaDB Vectors),
and fuses results using Reciprocal Rank Fusion (RRF) before prompting Gemini for citations.
"""

from __future__ import annotations

import logging
import json
from shared.database import get_config, fts_search
from rag.embedder import GeminiEmbedder
from rag.vectorstore import ChromaVectorStore
from shared.gemini_client import query_gemini_api

from typing import Any

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")


class RAGPipeline:
    """
    Self-Querying Hybrid RAG pipeline combining SQLite FTS5 & ChromaDB Vector Search.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or get_config("gemini_api_key")
        self.embedder = GeminiEmbedder(api_key=self.api_key)
        self.vector_store = ChromaVectorStore()

    def _parse_query_intent(self, question: str) -> dict[str, str]:
        """
        Self-Querying Parser: Deconstructs user prompt into FTS5 keywords and semantic vector text.
        """
        parser_prompt = (
            "You are a search query optimizer for an enterprise assistant. "
            "Analyze the user's input question and extract two clean search components as JSON:\n"
            "1. 'fts_query': Clean keyword string for SQLite FTS5 keyword matching (remove conversational filler like 'hey buddy', 'can you find', etc.).\n"
            "2. 'semantic_query': Rephrased standalone semantic search string for vector embedding.\n\n"
            f"User Question: \"{question}\"\n\n"
            "Return JSON format strictly: {\"fts_query\": \"...\", \"semantic_query\": \"...\"}"
        )
        try:
            raw_json = query_gemini_api(
                parser_prompt,
                api_key=self.api_key,
                task_type="rag_parse"
            )
            parsed = json.loads(raw_json)
            return {
                "fts_query": parsed.get("fts_query", question),
                "semantic_query": parsed.get("semantic_query", question)
            }
        except Exception as e:
            logging.warning(f"[RAGPipeline] Self-query parsing notice: {e}. Falling back to raw query.")
            return {"fts_query": question, "semantic_query": question}

    def query(self, question: str, metadata_filters: dict[str, Any] | None = None, chat_history: list[dict] | None = None) -> dict[str, Any]:
        """
        Execute Self-Querying Hybrid RAG:
        1. Deconstruct query intent.
        2. Execute ChromaDB vector search & SQLite FTS5 keyword search in parallel.
        3. Fuse rankings via Reciprocal Rank Fusion (RRF).
        4. Query Gemini LLM with context, conversational chat history memory, and render citations.
        """
        if not self.api_key:
            return {
                "answer": "AI Chatbot is unavailable: Gemini API key is missing. Go to Settings to configure it.",
                "sources": [],
                "success": False
            }

        logging.info(f"[RAGPipeline] Processing question: '{question}'")

        try:
            # 1. Self-Query Parsing
            intent = self._parse_query_intent(question)
            fts_query_str = intent["fts_query"]
            semantic_query_str = intent["semantic_query"]

            # 2a. Dense Vector Search (ChromaDB)
            query_vector = self.embedder.embed_text(semantic_query_str)
            dense_matches = self.vector_store.search(query_vector, n_results=5, metadata_filters=metadata_filters)

            # 2b. Sparse Keyword Search (SQLite FTS5)
            fts_matches = fts_search(fts_query_str, limit=5)

            # 3. Reciprocal Rank Fusion (RRF)
            rrf_scores = {}
            doc_map = {}

            for rank, m in enumerate(dense_matches):
                tid = m["metadata"].get("thread_id") or m["id"]
                score = 1.0 / (60 + (rank + 1))
                rrf_scores[tid] = rrf_scores.get(tid, 0.0) + score
                doc_map[tid] = {
                    "text": m["text"],
                    "metadata": m["metadata"],
                    "relevance": m["relevance_score"]
                }

            for rank, f in enumerate(fts_matches):
                tid = f.get("thread_id")
                if not tid:
                    continue
                score = 1.0 / (60 + (rank + 1))
                rrf_scores[tid] = rrf_scores.get(tid, 0.0) + score

                if tid not in doc_map:
                    doc_map[tid] = {
                        "text": f.get("raw_text", "")[:1500],
                        "metadata": {
                            "thread_id": tid,
                            "subject": f.get("subject", "No Subject"),
                            "thread_date": f.get("thread_date", f.get("first_message_at", "")[:10]),
                            "source": f.get("source", "unknown"),
                            "team_name": f.get("team_name", ""),
                            "channel_name": f.get("channel_name", ""),
                            "participants": f.get("participants", "Unknown")
                        },
                        "relevance": 0.85
                    }

            if not doc_map:
                return {
                    "answer": "I scanned the organizational message history but could not find any discussions relevant to your question.",
                    "sources": [],
                    "success": True
                }

            sorted_tids = sorted(rrf_scores.keys(), key=lambda k: rrf_scores[k], reverse=True)[:5]
            fused_matches = [doc_map[tid] for tid in sorted_tids]

            # 4. Format context block and source citations
            context_blocks = []
            unique_sources = {}

            for m in fused_matches:
                context_blocks.append(m["text"])
                meta = m["metadata"]
                tid = meta.get("thread_id")
                
                if tid and tid not in unique_sources:
                    raw_src = (meta.get("source") or "teams").lower()
                    clean_src = "outlook" if ("outlook" in raw_src or "mail" in raw_src) else "teams"
                    unique_sources[tid] = {
                        "thread_id": tid,
                        "subject": meta.get("subject", "Communication Thread"),
                        "date": meta.get("thread_date", "Recent"),
                        "source": clean_src,
                        "team_name": meta.get("team_name", ""),
                        "channel_name": meta.get("channel_name", ""),
                        "participants": meta.get("participants", "Team Members"),
                        "relevance": m.get("relevance", 0.85),
                        "text": m.get("text", "")
                    }

            context_str = "\n\n---\n\n".join(context_blocks)

            # Format prior chat history turns if provided
            history_blocks = []
            if chat_history:
                for turn in chat_history[-6:]:
                    sender = "Founder" if turn.get("sender") == "user" else "Buddy"
                    history_blocks.append(f"{sender}: {turn.get('text', '')}")
            history_str = "\n".join(history_blocks) if history_blocks else "None"

            # 5. Construct RAG Prompt
            from shared.model_router import router as model_router
            rag_model = model_router.select_model("rag_query")
            
            prompt = (
                "You are 'Buddy', an intelligent operational assistant for the company founder. "
                "Your task is to answer the user's question based on the retrieved workspace communication context "
                "and prior conversation thread memory.\n\n"
                "Adhere to these rules:\n"
                "1. Cite the relevant thread subjects, dates, and channel/email sources in your explanation.\n"
                "2. Maintain conversational memory from prior turns in this chat session.\n"
                "3. If context does not contain relevant info, state clearly what is missing.\n"
                "4. Keep your response structured, concise, and professional.\n\n"
                f"--- PRIOR CHAT HISTORY MEMORY ---\n{history_str}\n\n"
                f"--- RETRIEVED WORKSPACE CONTEXT ---\n{context_str}\n--- END CONTEXT ---\n\n"
                f"User Question: {question}\n\n"
                "Answer (in clean Markdown format):"
            )

            # 6. Call Gemini LLM
            logging.info(f"[RAGPipeline] Querying model '{rag_model}' with fused context...")
            answer = query_gemini_api(
                prompt,
                api_key=self.api_key,
                model_name=rag_model,
                task_type="rag_query"
            )

            return {
                "answer": answer,
                "sources": sorted(list(unique_sources.values()), key=lambda x: x["relevance"], reverse=True),
                "success": True
            }

        except Exception as e:
            logging.error(f"[RAGPipeline] Hybrid pipeline run failed: {e}", exc_info=True)
            return {
                "answer": f"An error occurred while retrieval searching: {str(e)}",
                "sources": [],
                "success": False
            }

