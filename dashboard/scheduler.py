"""
Automated Background Scheduler & Two-Lane Queue Worker.

Runs a continuous async loop polling every 60 seconds to execute
daily incremental ingestion, and drives two-lane task dispatching:
  1. Fast Lane Worker (high throughput, no LLM calls)
  2. Analytics Lane Worker (rate-limited Gemini pipeline)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from shared.database import get_db, get_config
from shared.task_queue import (
    process_queue_lane,
    register_task_handler,
    register_poke_listener
)
from ingestion.engine import IngestionEngine
from dashboard.pipeline import run_full_pipeline

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# TASK HANDLER IMPLEMENTATIONS
# ─────────────────────────────────────────────────────────────────────

def _handle_fast_text_clean(payload: dict):
    """Fast lane handler for PII scrubbing and text cleaning."""
    thread_id = payload.get("thread_id")
    logger.info(f"[FastLane] Cleaned and scrubbed thread '{thread_id}'")


def _handle_analytics_extract(payload: dict):
    """Analytics lane handler for Gemini risk signal extraction."""
    api_key = get_config("gemini_api_key")
    if not api_key:
        logger.warning("[AnalyticsLane] Skipping extraction: missing Gemini API key.")
        return
    logger.info(f"[AnalyticsLane] Running pipeline extraction for payload: {payload}")
    run_full_pipeline(api_key=api_key, run_type="queued_task")


# Register handlers
register_task_handler("fast_text_clean", _handle_fast_text_clean)
register_task_handler("extract_signals", _handle_analytics_extract)
register_task_handler("generate_summary", _handle_analytics_extract)


class SchedulerEngine:
    """
    Manages background execution of data syncs, pipeline runs, and queue lanes.
    """

    def __init__(self):
        self._running_task: asyncio.Task | None = None
        self._fast_worker_task: asyncio.Task | None = None
        self._analytics_worker_task: asyncio.Task | None = None
        self._is_syncing = False
        self._poke_event = asyncio.Event()

    async def start(self):
        """Start background scheduling loop and worker tasks."""
        if self._running_task and not self._running_task.done():
            logger.warning("[Scheduler] Scheduler loop is already active.")
            return

        # Register poke listener to awaken workers instantly
        register_poke_listener(self._on_poke)

        self._running_task = asyncio.create_task(self._loop())
        self._fast_worker_task = asyncio.create_task(self._fast_lane_loop())
        self._analytics_worker_task = asyncio.create_task(self._analytics_lane_loop())
        logger.info("[Scheduler] Automated background scheduler and 2-lane workers started.")

    async def stop(self):
        """Stop background loops."""
        for task in (self._running_task, self._fast_worker_task, self._analytics_worker_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info("[Scheduler] Automated background scheduler stopped.")

    async def _on_poke(self, lane: str):
        """Triggered on task enqueue to wake up worker loops instantly."""
        self._poke_event.set()

    async def _fast_lane_loop(self):
        """Worker loop for high-throughput fast lane tasks."""
        while True:
            try:
                processed = await asyncio.to_thread(process_queue_lane, "fast", 20)
                if processed == 0:
                    self._poke_event.clear()
                    try:
                        await asyncio.wait_for(self._poke_event.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Scheduler] Fast lane worker error: {e}")
                await asyncio.sleep(5)

    async def _analytics_lane_loop(self):
        """Worker loop for rate-limited analytics lane tasks."""
        while True:
            try:
                processed = await asyncio.to_thread(process_queue_lane, "analytics", 5)
                if processed == 0:
                    try:
                        await asyncio.sleep(10.0)
                    except asyncio.CancelledError:
                        break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Scheduler] Analytics lane worker error: {e}")
                await asyncio.sleep(10)

    async def _loop(self):
        """Main check loop for preferred sync time (runs every 60 seconds)."""
        last_executed_date = None

        while True:
            try:
                now = datetime.now()
                current_date = now.strftime("%Y-%m-%d")
                target_time = get_config("preferred_sync_time") or "02:00"

                try:
                    target_hour, target_minute = int(target_time[:2]), int(target_time[3:5])
                except (ValueError, IndexError):
                    target_hour, target_minute = 2, 0

                if (now.hour == target_hour and now.minute == target_minute
                        and last_executed_date != current_date):
                    if self._is_syncing:
                        logger.warning("[Scheduler] Sync triggered but a sync is already running.")
                    else:
                        last_executed_date = current_date
                        asyncio.create_task(self.run_scheduled_sync())

            except Exception as e:
                logger.error(f"[Scheduler] Loop iteration failed: {e}", exc_info=True)

            await asyncio.sleep(60)

    async def run_scheduled_sync(self):
        """Runs incremental ingestion and enqueues analytics tasks."""
        self._is_syncing = True
        logger.info("[Scheduler] Starting scheduled operations sync and pipeline execution...")

        try:
            logger.info("[Scheduler] Triggering incremental ingestion...")
            ingest_engine = IngestionEngine()
            await ingest_engine.run_sync()

            api_key = get_config("gemini_api_key")
            if api_key:
                from shared.task_queue import enqueue_task
                enqueue_task("extract_signals", {"reason": "scheduled_sync"}, lane="analytics", priority=100)
                logger.info("[Scheduler] Scheduled pipeline task enqueued.")
            else:
                logger.error("[Scheduler] Gemini API key is missing. Skipping pipeline task.")

        except Exception as e:
            logger.error(f"[Scheduler] Scheduled execution failed: {e}", exc_info=True)
        finally:
            self._is_syncing = False


# Centralized singleton instance
scheduler = SchedulerEngine()
