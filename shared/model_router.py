"""
Smart Model Router — Multi-model Routing with Token Budget & Quota Tracking.

Selects the optimal Gemini text generation model per pipeline task type based on:
  1. Task classification (Lite-first vs Non-Lite primary).
  2. Daily request quota tracking (resets at midnight UTC).
  3. Per-task primary + fallback model chains.

Model Catalogue (Confirmed Google AI Studio v1beta):
  - gemini-3.5-flash-lite (15 RPM / 250K TPM / 500 RPD - Newer Lite)
  - gemini-3.1-flash-lite (15 RPM / 250K TPM / 500 RPD - Older Lite)
  - gemini-3-flash       ( 5 RPM / 250K TPM / 500 RPD - Non-Lite)
  - gemini-3.5-flash     ( 5 RPM / 250K TPM /  20 RPD - Non-Lite)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import NamedTuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# CUSTOM EXCEPTION — raised when daily RPD quota is exhausted
# ─────────────────────────────────────────────────────────────────────

class QuotaExhaustedError(Exception):
    """
    Raised when a model's daily request quota (RPD) has been exhausted.
    Carries enough context for the pipeline to persist a savepoint.
    """
    def __init__(self, model: str, task_type: str, run_id: str = "", batch_index: int = 0):
        self.model = model
        self.task_type = task_type
        self.run_id = run_id
        self.batch_index = batch_index
        super().__init__(
            f"Daily quota exhausted for model '{model}' on task '{task_type}' "
            f"(run={run_id}, batch={batch_index}). A savepoint will be created."
        )


class PipelinePausedError(Exception):
    """
    Raised by the pipeline orchestrator after a savepoint has been persisted.
    Signals the API layer to return a 'paused' state to the frontend.
    """
    def __init__(self, savepoint_id: str, stage: str, message: str):
        self.savepoint_id = savepoint_id
        self.stage = stage
        self.message = message
        super().__init__(message)


# ─────────────────────────────────────────────────────────────────────
# MODEL CATALOGUE
# ─────────────────────────────────────────────────────────────────────

class ModelSpec(NamedTuple):
    model_id: str            # Exact Gemini REST API model name
    rpm: int                 # Requests Per Minute limit
    tpm: int                 # Tokens Per Minute limit (input)
    rpd: int                 # Requests Per Day limit (0 = unlimited)
    display_name: str        # Human-readable name for UI / logs


MODEL_CATALOGUE: dict[str, ModelSpec] = {
    "gemini-3.5-flash-lite": ModelSpec(
        model_id="gemini-3.5-flash-lite",
        rpm=15,
        tpm=250_000,
        rpd=500,
        display_name="Gemini 3.5 Flash Lite"
    ),
    "gemini-3.1-flash-lite": ModelSpec(
        model_id="gemini-3.1-flash-lite",
        rpm=15,
        tpm=250_000,
        rpd=500,
        display_name="Gemini 3.1 Flash Lite"
    ),
    "gemini-3.5-flash": ModelSpec(
        model_id="gemini-3.5-flash",
        rpm=5,
        tpm=250_000,
        rpd=500,
        display_name="Gemini 3.5 Flash"
    ),
}

# ─────────────────────────────────────────────────────────────────────
# TASK ROUTING TABLE
# primary → fallback chain per pipeline task type (Gemini 3.x models ONLY)
# ─────────────────────────────────────────────────────────────────────

TASK_ROUTING: dict[str, list[str]] = {
    # ── Lite-First Tasks (Lite Models First -> Non-Lite Fallback) ──
    "event_extraction":   ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.5-flash"],
    "signal_clustering":  ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.5-flash"],
    "rag_parse":          ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.5-flash"],
    "test_connection":    ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.5-flash"],

    # ── Non-Lite Primary Tasks (Gemini 3.5 Flash Primary -> Lite Fallback) ──
    "rag_query":          ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"],
    "cluster_health":     ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"],
    "summary":            ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"],
}

# ─────────────────────────────────────────────────────────────────────
# DAILY COUNTER HELPERS (backed by SQLite config table)
# ─────────────────────────────────────────────────────────────────────

def _today_key(model_id: str) -> str:
    """Returns config key for today's request counter for a given model."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"quota_count_{model_id}_{today}"


def _get_daily_count(model_id: str) -> int:
    """Reads today's request count from the SQLite config table."""
    try:
        from shared.database import get_config
        raw = get_config(_today_key(model_id))
        return int(raw) if raw else 0
    except Exception:
        return 0


def _increment_daily_count(model_id: str) -> int:
    """Atomically increments and persists today's request count. Returns new count."""
    try:
        from shared.database import set_config, get_config
        key = _today_key(model_id)
        current = int(get_config(key) or 0)
        new_count = current + 1
        set_config(key, str(new_count))
        return new_count
    except Exception as e:
        logging.warning(f"[ModelRouter] Failed to update daily counter for {model_id}: {e}")
        return 0


def _is_quota_exhausted(model_id: str) -> bool:
    """
    Checks if the daily RPD quota for a model has been reached.
    Returns False for models with rpd == 0 (treated as unlimited).
    """
    spec = MODEL_CATALOGUE.get(model_id)
    if not spec or spec.rpd == 0:
        return False
    count = _get_daily_count(model_id)
    return count >= spec.rpd


# ─────────────────────────────────────────────────────────────────────
# CORE ROUTER
# ─────────────────────────────────────────────────────────────────────

class ModelRouter:
    """
    Selects the best available model for a given task type and estimated token count.
    Maintains soft daily quota tracking and raises QuotaExhaustedError when all
    models in a task's fallback chain are exhausted.
    """

    def is_daily_quota_exhausted(self, model_id: str) -> bool:
        """Returns True if model_id has reached its daily RPD limit."""
        return _is_quota_exhausted(model_id)

    def get_daily_limit(self, model_id: str) -> int:
        """Returns daily RPD limit for model_id."""
        spec = MODEL_CATALOGUE.get(model_id)
        return spec.rpd if spec else 0

    def get_min_spacing(self, model_id: str) -> float:
        """
        Calculates per-model minimum seconds between consecutive requests based on its
        configured RPM (Requests Per Minute) in MODEL_CATALOGUE.
        """
        spec = MODEL_CATALOGUE.get(model_id)
        if not spec or spec.rpm <= 0:
            return 2.0
        return round((60.0 / spec.rpm) + 0.1, 2)

    def select_model(
        self,
        task_type: str,
        estimated_tokens: int = 0,
        run_id: str = "",
        batch_index: int = 0
    ) -> str:
        """
        Returns the model_id string to use for this specific call.

        Selection logic:
        1. Iterate through the fallback chain for task_type.
        2. Skip models whose daily RPD quota is exhausted.
        3. Return the first valid model.
        4. If all models are exhausted, raise QuotaExhaustedError.
        """
        chain = TASK_ROUTING.get(task_type, ["gemini-3.5-flash-lite"])

        for model_id in chain:
            spec = MODEL_CATALOGUE.get(model_id)

            # Check daily quota
            if _is_quota_exhausted(model_id):
                logger.warning(
                    f"[ModelRouter] '{model_id}' daily quota exhausted "
                    f"({_get_daily_count(model_id)} / {spec.rpd if spec else '?'} RPD). "
                    f"Trying next in chain..."
                )
                continue

            logger.info(
                f"[ModelRouter] Selected '{model_id}' ({spec.display_name if spec else model_id}) "
                f"for task '{task_type}' | est. tokens: {estimated_tokens}"
            )
            return model_id

        # All models in chain are exhausted
        exhausted_model = chain[0] if chain else "unknown"
        raise QuotaExhaustedError(
            model=exhausted_model,
            task_type=task_type,
            run_id=run_id,
            batch_index=batch_index
        )

    def record_request(self, model_id: str) -> None:
        """
        Must be called after every successful API request to a model.
        Increments the daily usage counter for quota tracking.
        """
        new_count = _increment_daily_count(model_id)
        spec = MODEL_CATALOGUE.get(model_id)
        if spec and spec.rpd > 0:
            remaining = spec.rpd - new_count
            logger.debug(
                f"[ModelRouter] '{model_id}' daily usage: {new_count}/{spec.rpd} "
                f"({remaining} remaining today)"
            )

    def get_quota_status(self) -> dict[str, dict]:
        """
        Returns current daily quota usage for all tracked models.
        Used by dashboard status endpoints.
        """
        result = {}
        for model_id, spec in MODEL_CATALOGUE.items():
            count = _get_daily_count(model_id)
            result[model_id] = {
                "display_name": spec.display_name,
                "used_today": count,
                "daily_limit": spec.rpd,
                "remaining": max(0, spec.rpd - count) if spec.rpd > 0 else "unlimited",
                "exhausted": _is_quota_exhausted(model_id)
            }
        return result

    def format_quota_warning(self, model_id: str) -> str:
        """Returns a human-readable quota warning string for the UI."""
        spec = MODEL_CATALOGUE.get(model_id)
        if not spec:
            return f"Model '{model_id}' quota information unavailable."
        count = _get_daily_count(model_id)
        return (
            f"The **{spec.display_name}** model has reached its daily request limit "
            f"({count}/{spec.rpd} requests used). "
            f"Your quota resets at midnight UTC. "
            f"To continue immediately, please upgrade your Gemini API plan at "
            f"https://aistudio.google.com/apikey."
        )


# Singleton instance for use across all modules
router = ModelRouter()
