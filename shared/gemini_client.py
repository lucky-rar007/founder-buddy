"""
Shared Gemini API Client.

Centralized HTTP client for Google Generative AI (Gemini) REST calls.
Includes:
  - Smart model routing via ModelRouter (Gemini Flash / Flash Lite fallback chains)
  - Rate limiting throttle (min 2s spacing between calls)
  - Exponential backoff on transient 429/503 errors
  - Quota exhaustion detection: distinguishes RATE_LIMIT (retry) vs RESOURCE_EXHAUSTED (fatal)
  - JSON response enforcement
  - Prompt template loader
"""

from __future__ import annotations

import os
import time
import random
import logging
import requests
import json

from shared.model_router import router, QuotaExhaustedError

logger = logging.getLogger(__name__)

_last_request_times: dict[str, float] = {}


def query_gemini_api(
    prompt: str,
    model_name: str | None = None,
    api_key: str | None = None,
    task_type: str = "general",
    estimated_tokens: int = 0,
    run_id: str = "",
    batch_index: int = 0
) -> str:
    """
    Sends prompt to Gemini using REST API with x-goog-api-key header authentication.

    Args:
        prompt: The prompt text to send.
        model_name: Override model name (bypasses ModelRouter if provided).
        api_key: Gemini API key (reads from DB/env if not provided).
        task_type: Pipeline stage key for ModelRouter routing (e.g. 'event_extraction').
        estimated_tokens: Pre-calculated token estimate for model selection.
        run_id: Current pipeline run ID (forwarded to QuotaExhaustedError context).
        batch_index: Current batch index (forwarded to QuotaExhaustedError context).

    Returns:
        Raw text response from the model.

    Raises:
        QuotaExhaustedError: When all models in the fallback chain hit daily RPD limits.
        Exception: On unrecoverable API errors after max retries.
    """
    # ── Resolve API key ────────────────────────────────────────
    if not api_key:
        api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        try:
            from shared.database import get_config
            api_key = get_config("gemini_api_key")
        except Exception:
            pass

    if not api_key:
        raise ValueError("Gemini API Key is missing. Set GEMINI_API_KEY or configure it in Settings.")

    # ── Resolve Model Name ────────────────────────────────────
    if not model_name:
        # Use ModelRouter to pick the best model for this task type and token budget
        model_name = router.select_model(
            task_type=task_type,
            estimated_tokens=estimated_tokens,
            run_id=run_id,
            batch_index=batch_index
        )

    # ── Per-Model Rate-Limit Throttle (calculates spacing dynamically from model's RPM) ──
    min_spacing = router.get_min_spacing(model_name)
    last_time = _last_request_times.get(model_name, 0.0)
    elapsed = time.time() - last_time
    if elapsed < min_spacing:
        sleep_time = min_spacing - elapsed + random.uniform(0.1, 0.4)
        logger.info(f"[GeminiClient] Rate-limit throttle for '{model_name}' (spacing: {min_spacing:.1f}s). Sleeping {sleep_time:.2f}s...")
        time.sleep(sleep_time)

    # ── Build Request ─────────────────────────────────────────
    mime_type = "text/plain" if task_type in ("rag_query", "general_text") else "application/json"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": mime_type,
            "temperature": 0.1
        }
    }
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key
    }

    max_retries = 5
    base_backoff = 3.0

    for attempt in range(1, max_retries + 1):
        _last_request_times[model_name] = time.time()
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=90)

            # ── Transient rate-limit or server error → retry ──
            if response.status_code in (429, 503):
                # Check if ACTUAL daily RPD quota is exhausted in SQLite database
                if router.is_daily_quota_exhausted(model_name):
                    logging.error(
                        f"[GeminiClient] Daily RPD quota ({router.get_daily_limit(model_name)}) "
                        f"exhausted for model '{model_name}'. Raising QuotaExhaustedError."
                    )
                    raise QuotaExhaustedError(
                        model=model_name,
                        task_type=task_type,
                        run_id=run_id,
                        batch_index=batch_index
                    )

                # Not daily exhausted -> this is a transient RPM rate limit throttle (e.g. >15 req/min)!
                backoff = (base_backoff ** attempt) + random.uniform(1.0, 3.0)
                logger.warning(
                    f"[GeminiClient] HTTP 429 RPM Rate Limit for '{model_name}' "
                    f"(Attempt {attempt}/{max_retries}). Daily quota is NOT exhausted. Retrying in {backoff:.1f}s..."
                )
                time.sleep(backoff)
                continue

            if response.status_code == 404:
                logger.warning(
                    f"[GeminiClient] Model '{model_name}' returned HTTP 404 Not Found from Google API. "
                    f"Marking model unavailable to trigger task fallback."
                )
                raise QuotaExhaustedError(
                    model=model_name,
                    task_type=task_type,
                    run_id=run_id,
                    batch_index=batch_index
                )

            if response.status_code != 200:
                raise Exception(
                    f"Gemini API returned error status {response.status_code}: {response.text}"
                )

            res_data = response.json()
            content_text = res_data["candidates"][0]["content"]["parts"][0]["text"]

            # ── Record successful request against daily counter ──
            router.record_request(model_name)

            return content_text

        except QuotaExhaustedError:
            raise  # Re-raise immediately — do not retry a quota exhaustion

        except (requests.exceptions.RequestException, KeyError, IndexError) as e:
            if attempt == max_retries:
                raise Exception(
                    f"Failed to query Gemini API after {max_retries} attempts: {str(e)}"
                )
            backoff = (base_backoff ** attempt) + random.uniform(0.5, 1.5)
            logger.warning(
                f"[GeminiClient] Error on attempt {attempt}/{max_retries}: {str(e)}. "
                f"Retrying in {backoff:.2f}s..."
            )
            time.sleep(backoff)

    raise Exception("Failed to query Gemini API after maximum retries.")


def load_prompt_template(filename: str, prompt_dir: str | None = None) -> str:
    """Loads a raw prompt template file."""
    if prompt_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        prompt_dir = os.path.join(os.path.dirname(base_dir), "dashboard", "prompts")

    path = os.path.join(prompt_dir, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def clean_json_text(text: str) -> str:
    """Strips markdown code blocks ```json ... ``` and leading/trailing whitespace from LLM text responses."""
    if not text:
        return ""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text
