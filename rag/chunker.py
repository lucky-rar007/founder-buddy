"""
Thread Chunker.

Splits structured threads into context-preserved chunks optimized for vector search.
"""

from __future__ import annotations

import json
import logging

from typing import Any

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")


class ThreadChunker:
    """
    Chunks large thread raw texts into retrieval blocks with overlapping boundaries,
    ensuring each block carries full conversation context headers.
    """

    def __init__(self, chunk_size: int = 4000, overlap: int = 500) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_thread(self, thread: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Slice a thread dict into one or more chunks.
        Returns a list of chunk dicts:
        {
            "doc_id": "doc_th_xxx_0",
            "thread_id": "th_xxx",
            "chunk_index": 0,
            "chunk_text": "...",
            "metadata_json": "..."
        }
        """
        thread_id = thread.get("thread_id")
        raw_text = thread.get("raw_text", "") or ""
        subject = thread.get("subject", "No Subject")
        thread_date = thread.get("thread_date", "No Date")
        source = thread.get("source", "unknown")
        team = thread.get("team_name")
        channel = thread.get("channel_name")
        participants = thread.get("participants", "Unknown")

        # Compile header prepended to every chunk
        location = f"{team} > #{channel}" if source == "teams" else "Outlook Inbox"
        header = (
            f"=== CONVERSATION CONTEXT ===\n"
            f"Subject: {subject}\n"
            f"Date: {thread_date}\n"
            f"Source: {source.upper()} ({location})\n"
            f"Participants: {participants}\n"
            f"=============================\n\n"
        )

        # If text is small, index it as a single chunk
        if len(raw_text) <= self.chunk_size:
            chunk_body = raw_text
            full_text = header + chunk_body
            return [{
                "doc_id": f"doc_{thread_id}_0",
                "thread_id": thread_id,
                "chunk_index": 0,
                "chunk_text": full_text,
                "metadata_json": json.dumps({
                    "thread_id": thread_id,
                    "subject": subject,
                    "thread_date": thread_date,
                    "source": source,
                    "team_name": team or "",
                    "channel_name": channel or "",
                    "participants": participants
                })
            }]

        # Slide chunks
        chunks = []
        start = 0
        chunk_idx = 0
        
        while start < len(raw_text):
            end = start + self.chunk_size
            chunk_body = raw_text[start:end]
            full_text = header + chunk_body
            
            chunks.append({
                "doc_id": f"doc_{thread_id}_{chunk_idx}",
                "thread_id": thread_id,
                "chunk_index": chunk_idx,
                "chunk_text": full_text,
                "metadata_json": json.dumps({
                    "thread_id": thread_id,
                    "subject": subject,
                    "thread_date": thread_date,
                    "source": source,
                    "team_name": team or "",
                    "channel_name": channel or "",
                    "participants": participants
                })
            })
            
            chunk_idx += 1
            start += (self.chunk_size - self.overlap)
            
        return chunks
