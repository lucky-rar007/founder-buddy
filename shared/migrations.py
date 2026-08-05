"""
Database Migration System.

Provides versioned schema migration handling for SQLite database updates.
Ensures production database updates can be applied sequentially without data loss.
"""

from __future__ import annotations

import logging
from shared.database import get_db, get_config, set_config

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 2


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

        if current_version < 2:
            # Version 2: Agent tasks queue and dragging_issues recheck columns
            conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_tasks (
                task_id          TEXT PRIMARY KEY,
                kind             TEXT NOT NULL,
                lane             TEXT DEFAULT 'analytics',
                payload_json     TEXT NOT NULL,
                priority         INTEGER DEFAULT 100,
                status           TEXT DEFAULT 'pending',
                attempts         INTEGER DEFAULT 0,
                error_message    TEXT,
                lease_expires_at TEXT,
                created_at       TEXT DEFAULT (datetime('now')),
                updated_at       TEXT DEFAULT (datetime('now'))
            );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_tasks_status ON agent_tasks(status, lane, priority DESC);")

            cursor = conn.execute("PRAGMA table_info(dragging_issues)")
            cols = [row[1] for row in cursor.fetchall()]
            if "recheck_after" not in cols:
                conn.execute("ALTER TABLE dragging_issues ADD COLUMN recheck_after TEXT;")
            if "recheck_reason" not in cols:
                conn.execute("ALTER TABLE dragging_issues ADD COLUMN recheck_reason TEXT;")

    set_config("schema_version", str(CURRENT_SCHEMA_VERSION))
    logger.info(f"[Migration] Schema upgraded successfully to version {CURRENT_SCHEMA_VERSION}.")
