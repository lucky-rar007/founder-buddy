"""
RAG Chat API Routes.

Handles natural language searches over message threads and vectors indexing triggers.
"""

from __future__ import annotations

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from shared.database import get_db, get_config
from rag.pipeline import RAGPipeline
from rag.indexer import ThreadIndexer
from rag.vectorstore import ChromaVectorStore

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────
# REQUEST SCHEMAS
# ─────────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str
    thread_id: Optional[str] = None
    filters: Optional[dict] = None


class ThreadCreateRequest(BaseModel):
    title: Optional[str] = "New Chat"


class IndexRequest(BaseModel):
    clear_first: Optional[bool] = False


# ─────────────────────────────────────────────────────────────────────
# THREAD & SESSION MANAGEMENT ENDPOINTS
# ─────────────────────────────────────────────────────────────────────

@router.get("/threads")
async def list_chat_threads():
    """List all RAG chat sessions."""
    from dashboard.db import get_chat_threads
    return {"success": True, "threads": get_chat_threads()}


@router.post("/threads")
async def create_new_chat_thread(req: ThreadCreateRequest):
    """Create a new RAG chat session."""
    from dashboard.db import create_chat_thread
    thread = create_chat_thread(title=req.title or "New Chat")
    return {"success": True, "thread": thread}


@router.delete("/threads/{thread_id}")
async def remove_chat_thread(thread_id: str):
    """Delete a RAG chat session and its stored history."""
    from dashboard.db import delete_chat_thread
    delete_chat_thread(thread_id)
    return {"success": True, "message": f"Chat session {thread_id} deleted."}


@router.get("/threads/{thread_id}/messages")
async def list_chat_messages(thread_id: str):
    """Retrieve message history for a specific chat session."""
    from dashboard.db import get_chat_messages
    return {"success": True, "messages": get_chat_messages(thread_id)}


# ─────────────────────────────────────────────────────────────────────
# QUERY ENDPOINT WITH CONVERSATIONAL MEMORY
# ─────────────────────────────────────────────────────────────────────

@router.post("/query")
async def chat_query(req: QueryRequest):
    """
    Query the chatbot with a natural language question.
    Saves message history to thread, uses memory, and returns answer + citations.
    """
    from dashboard.db import create_chat_thread, get_chat_messages, add_chat_message

    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    if len(req.question.strip()) > 2000:
        raise HTTPException(status_code=400, detail="Question exceeds maximum length of 2000 characters.")

    # Ensure valid thread ID
    thread_id = req.thread_id
    if not thread_id:
        new_t = create_chat_thread(title=req.question.strip()[:36])
        thread_id = new_t["thread_id"]

    try:
        # Fetch prior chat history for memory
        prior_messages = get_chat_messages(thread_id)

        # Append user message turn to SQLite
        add_chat_message(thread_id, sender="user", text=req.question.strip())

        # Execute RAG query with conversational memory
        pipeline = RAGPipeline()
        res = pipeline.query(req.question.strip(), metadata_filters=req.filters, chat_history=prior_messages)

        # Append bot response turn to SQLite
        if res.get("success"):
            add_chat_message(thread_id, sender="bot", text=res["answer"], sources=res.get("sources", []))

        res["thread_id"] = thread_id
        return res
    except Exception as e:
        logging.error(f"[RAG API] Q&A query failure: {e}", exc_info=True)
        return {
            "answer": f"An error occurred while searching: {str(e)}",
            "sources": [],
            "thread_id": thread_id,
            "success": False
        }


@router.post("/index")
async def trigger_indexing(req: IndexRequest, background_tasks: BackgroundTasks):
    """
    Trigger incremental vector store indexing of SQLite threads in background.
    """
    api_key = get_config("gemini_api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail="Gemini API Key is missing. Configure it in settings first.")

    def run_indexing():
        try:
            indexer = ThreadIndexer(api_key=api_key)
            indexer.index_pending_threads(clear_first=req.clear_first)
        except Exception as e:
            logging.error(f"[RAG API Background Index] Indexing failed: {e}")

    background_tasks.add_task(run_indexing)
    return {"success": True, "message": "Indexing started in the background."}


@router.get("/status")
async def indexing_status():
    """
    Get the current vector store index size and status metrics.
    """
    try:
        vector_store = ChromaVectorStore()
        chunks_count = vector_store.get_count()

        threads_count = 0
        with get_db() as conn:
            row = conn.execute("SELECT COUNT(DISTINCT thread_id) FROM rag_documents").fetchone()
            if row:
                threads_count = row[0]

        return {
            "success": True,
            "indexed_chunks": chunks_count,
            "indexed_threads": threads_count,
            "is_indexed": chunks_count > 0
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/thread/{thread_id}")
async def get_thread_details(thread_id: str):
    """
    Get raw text and full context details for a single thread.
    Used by citation cards popup modal in UI.
    """
    try:
        with get_db() as conn:
            row = conn.execute(
                """SELECT thread_id, source, subject, participants, thread_date, team_name, channel_name, raw_text
                   FROM threads WHERE thread_id = ?""", (thread_id,)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Thread not found.")
            return {"success": True, "thread": dict(row)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
