"""
Automated Background Scheduler.

Runs a continuous async loop polling every 60 seconds to execute
daily incremental ingestion and pipeline runs at the user's preferred time.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from shared.database import get_db, get_config
from ingestion.engine import IngestionEngine
from dashboard.pipeline import run_full_pipeline

logger = logging.getLogger(__name__)


class SchedulerEngine:
    """
    Manages background execution of data syncs and pipeline runs.
    """

    def __init__(self):
        self._running_task: asyncio.Task | None = None
        self._is_syncing = False

    async def start(self):
        """Start the background scheduling loop."""
        if self._running_task and not self._running_task.done():
            logging.warning("[Scheduler] Scheduler loop is already active.")
            return

        self._running_task = asyncio.create_task(self._loop())
        logger.info("[Scheduler] Automated background scheduler started successfully.")

    async def stop(self):
        """Stop the background scheduling loop."""
        if self._running_task:
            self._running_task.cancel()
            try:
                await self._running_task
            except asyncio.CancelledError:
                pass
            logger.info("[Scheduler] Automated background scheduler stopped.")

    async def _loop(self):
        """Main check loop, runs every 60 seconds."""
        # Keep track of the last time we executed to prevent double triggering within the same minute
        last_executed_date = None

        while True:
            try:
                now = datetime.now()
                current_date = now.strftime("%Y-%m-%d")

                # Load target execution time (default: 02:00 AM)
                target_time = get_config("preferred_sync_time") or "02:00"

                # Parse target hour:minute for robust matching (immune to timing jitter)
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
                        # Run sync in background task
                        asyncio.create_task(self.run_scheduled_sync())

            except Exception as e:
                logger.error(f"[Scheduler] Loop iteration failed: {e}", exc_info=True)

            # Check every 60 seconds
            await asyncio.sleep(60)

    async def run_scheduled_sync(self):
        """Runs the incremental ingestion and full event pipeline sequentially."""
        self._is_syncing = True
        logger.info("[Scheduler] Starting scheduled operations sync and pipeline execution...")

        try:
            # 1. Trigger Ingestion to collect any new day-by-day JSON files
            logger.info("[Scheduler] Triggering incremental ingestion...")
            ingest_engine = IngestionEngine()
            await ingest_engine.run_sync()

            # 2. Trigger Event Extraction & Dashboard Scorecard generation
            logger.info("[Scheduler] Ingestion completed. Triggering pipeline execution...")
            api_key = get_config("gemini_api_key")
            if api_key:
                run_full_pipeline(api_key=api_key, run_type="automated")
                logger.info("[Scheduler] Scheduled dashboard pipeline executed successfully.")
            else:
                logger.error("[Scheduler] Gemini API key is missing. Skipping pipeline run.")

        except Exception as e:
            logger.error(f"[Scheduler] Scheduled execution failed: {e}", exc_info=True)
        finally:
            self._is_syncing = False


# Centralized singleton instance
scheduler = SchedulerEngine()
