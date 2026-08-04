"""
Gemini Embeddings Generator.

Generates vector embeddings using the model 'text-embedding-004' via REST API.
"""

from __future__ import annotations

import logging
import requests

from shared.database import get_config

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")


class GeminiEmbedder:
    """
    Client for the Gemini text-embedding-004 API.
    """

    MODEL = "models/gemini-embedding-001"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or get_config("gemini_api_key")

    def _get_headers(self) -> dict[str, str]:
        """Build authenticated request headers using x-goog-api-key (not URL params)."""
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

    def embed_text(self, text: str) -> list[float]:
        """Generate embedding vector for a single text string."""
        if not self.api_key:
            raise ValueError("Gemini API key is required to generate embeddings.")

        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent"
        payload = {
            "model": self.MODEL,
            "content": {
                "parts": [{"text": text}]
            }
        }

        try:
            response = requests.post(url, headers=self._get_headers(), json=payload, timeout=20.0)
            response.raise_for_status()
            data = response.json()
            return data["embedding"]["values"]
        except Exception as e:
            logging.error(f"[Embedder] Single embedding API call failed: {e}")
            raise

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embedding vectors for a batch of text strings.
        Gemini supports up to 100 texts in a batchEmbedContents request.
        """
        if not self.api_key:
            raise ValueError("Gemini API key is required to generate embeddings.")

        if not texts:
            return []

        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents"
        
        # Build individual requests list
        requests_list = []
        for text in texts:
            requests_list.append({
                "model": self.MODEL,
                "content": {
                    "parts": [{"text": text}]
                }
            })

        payload = {"requests": requests_list}

        try:
            response = requests.post(url, headers=self._get_headers(), json=payload, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            embeddings = [item["values"] for item in data["embeddings"]]
            return embeddings
        except Exception as e:
            logging.error(f"[Embedder] Batch embedding API call failed: {e}")
            raise
