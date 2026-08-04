"""
Database Migration System.

Provides versioned schema migration handling for SQLite database updates.
Ensures production database updates can be applied sequentially without data loss.
"""

from __future__ import annotations

import logging
from shared.database import get_db, get_config, set_config

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 1


def run_migrations() -> None:
    """
    Check current database schema version and apply any pending migrations.
    """
    version_str = get_config("schema_version")
    current_version = int(version_str) if version_str and version_str.isdigit() else 0

    if current_version >= CURRENT_SCHEMA_VERSION:
        return

    logger.info(f"[Migration] Upgrading database schema from version {current_version} to {CURRENT_SCHEMA_VERSION}...")

    with get_db() as conn:
        if current_version < 1:
            # Version 1: Initial schema baseline indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_threads_date ON threads(thread_date);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_thread ON events(thread_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_event ON signals(event_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_actionables_status ON actionables(status);")

    set_config("schema_version", str(CURRENT_SCHEMA_VERSION))
    logger.info(f"[Migration] Schema upgraded successfully to version {CURRENT_SCHEMA_VERSION}.")
