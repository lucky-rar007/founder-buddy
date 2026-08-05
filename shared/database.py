"""
Centralized SQLite Database Manager.

Manages the single SQLite database for the entire application:
configuration, ingestion state, threads, signals, summaries, and RAG metadata.

Uses WAL mode for better concurrent read/write performance.
Provides connection pooling via a thread-local connection pattern.
"""

from __future__ import annotations

import sqlite3
import os
import logging
import threading
import time as _time
from pathlib import Path
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# DATABASE PATH
# ─────────────────────────────────────────────────────────────────────

_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = _WORKSPACE_ROOT / "data"
DB_FILE = DB_DIR / "founder_buddy.db"

# Thread-local storage for connections
_local = threading.local()

# Maximum connection age in seconds before proactive recycling
_MAX_CONNECTION_AGE = 300  # 5 minutes


def get_connection() -> sqlite3.Connection:
    """
    Get a thread-local SQLite connection.

    Uses WAL journal mode for concurrent read/write.
    Returns the same connection per thread to avoid overhead.
    Proactively recycles connections older than 5 minutes.
    """
    conn = getattr(_local, "connection", None)
    created_at = getattr(_local, "connection_created_at", 0)

    if conn is not None:
        # Recycle stale connections proactively
        if (_time.time() - created_at) > _MAX_CONNECTION_AGE:
            try:
                conn.close()
            except Exception:
                pass
            conn = None
            _local.connection = None
        else:
            try:
                conn.execute("SELECT 1")
                return conn
            except sqlite3.ProgrammingError:
                # Connection was closed, create a new one
                _local.connection = None
                conn = None

    DB_DIR.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(str(DB_FILE), timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.row_factory = sqlite3.Row
        _local.connection = conn
        _local.connection_created_at = _time.time()
        return conn
    except sqlite3.OperationalError as e:
        logger.error(f"[Database] Failed to connect to {DB_FILE}: {e}")
        raise


@contextmanager
def get_db():
    """
    Context manager for database operations.

    Provides a connection and handles commit/rollback automatically.
    Usage:
        with get_db() as conn:
            conn.execute("INSERT INTO ...", (...))
    """
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def close_connection():
    """Close the thread-local connection if it exists."""
    conn = getattr(_local, "connection", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _local.connection = None


# ─────────────────────────────────────────────────────────────────────
# SCHEMA INITIALIZATION
# ─────────────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
-- ═══════════════════════════════════════════════════════
-- CONFIGURATION & STATE
-- ═══════════════════════════════════════════════════════

-- Application configuration (credentials, preferences)
CREATE TABLE IF NOT EXISTS app_config (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    encrypted   INTEGER DEFAULT 0,
    updated_at  TEXT DEFAULT (datetime('now'))
);

-- Ingestion state tracker (per source per day)
CREATE TABLE IF NOT EXISTS ingestion_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,
    source_entity   TEXT NOT NULL,
    target_date     TEXT NOT NULL,
    status          TEXT DEFAULT 'pending',
    messages_count  INTEGER DEFAULT 0,
    started_at      TEXT,
    completed_at    TEXT,
    error_message   TEXT,
    UNIQUE(source, source_entity, target_date)
);

-- Excluded channels/groups (user-selected during onboarding)
CREATE TABLE IF NOT EXISTS excluded_channels (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id      TEXT NOT NULL,
    team_name    TEXT,
    channel_id   TEXT NOT NULL,
    channel_name TEXT,
    excluded_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(team_id, channel_id)
);

-- Cron schedule configuration
CREATE TABLE IF NOT EXISTS cron_config (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════
-- SIGNAL & CLUSTER REGISTRIES
-- ═══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS signal_types (
    signal_type TEXT PRIMARY KEY,
    category    TEXT,
    description TEXT
);

CREATE TABLE IF NOT EXISTS clusters (
    cluster_type TEXT PRIMARY KEY,
    category     TEXT,
    description  TEXT,
    persistence  REAL DEFAULT 0.6,
    decay_rate   REAL DEFAULT 0.02
);

-- ═══════════════════════════════════════════════════════
-- THREADS (Output of Thread Builder)
-- ═══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS threads (
    thread_id        TEXT PRIMARY KEY,
    source           TEXT NOT NULL,
    source_id        TEXT,
    subject          TEXT,
    participants     TEXT,
    message_count    INTEGER DEFAULT 0,
    first_message_at TEXT,
    last_message_at  TEXT,
    raw_text         TEXT,
    team_name        TEXT,
    channel_name     TEXT,
    thread_date      TEXT,
    metadata_json    TEXT,
    created_at       TEXT DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════
-- EVENTS, SIGNALS, ACTIONABLES, DRAGGING ISSUES
-- ═══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS events (
    event_id        TEXT PRIMARY KEY,
    thread_id       TEXT REFERENCES threads(thread_id),
    signal_type     TEXT,
    impact_area     TEXT,
    direction       TEXT,
    confidence      REAL,
    summary         TEXT,
    timestamp       TEXT,
    pipeline_run_id TEXT
);

CREATE TABLE IF NOT EXISTS signals (
    signal_id        TEXT PRIMARY KEY,
    event_id         TEXT REFERENCES events(event_id),
    thread_id        TEXT REFERENCES threads(thread_id),
    signal_type      TEXT,
    cluster_type     TEXT,
    strength         REAL,
    decayed_strength REAL,
    persistence      REAL,
    decay_rate       REAL,
    relevance_score  REAL,
    confidence       REAL,
    timestamp        TEXT,
    pipeline_run_id  TEXT
);

CREATE TABLE IF NOT EXISTS actionables (
    actionable_id TEXT PRIMARY KEY,
    thread_id     TEXT REFERENCES threads(thread_id),
    event_id      TEXT REFERENCES events(event_id),
    title         TEXT,
    description   TEXT,
    priority      TEXT,
    status        TEXT DEFAULT 'open',
    source        TEXT,
    created_at    TEXT,
    due_date      TEXT,
    resolved_at   TEXT
);

CREATE TABLE IF NOT EXISTS dragging_issues (
    issue_id          TEXT PRIMARY KEY,
    thread_id         TEXT REFERENCES threads(thread_id),
    signal_id         TEXT REFERENCES signals(signal_id),
    title             TEXT,
    description       TEXT,
    days_unresolved   INTEGER,
    severity          TEXT,
    first_detected_at TEXT,
    last_checked_at   TEXT,
    recheck_after     TEXT,
    recheck_reason    TEXT,
    status            TEXT DEFAULT 'active'
);

-- ═══════════════════════════════════════════════════════
-- AGENT TASKS QUEUE (Asynchronous Task Dispatching)
-- ═══════════════════════════════════════════════════════

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

-- ═══════════════════════════════════════════════════════
-- SUMMARIES (Daily, Weekly, Monthly)
-- ═══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS summaries (
    summary_id       TEXT PRIMARY KEY,
    summary_type     TEXT NOT NULL,
    period_start     TEXT NOT NULL,
    period_end       TEXT NOT NULL,
    title            TEXT,
    content_json     TEXT NOT NULL,
    content_markdown TEXT,
    stats_json       TEXT,
    generated_at     TEXT DEFAULT (datetime('now')),
    pipeline_run_id  TEXT,
    UNIQUE(summary_type, period_start, period_end)
);

-- ═══════════════════════════════════════════════════════
-- PIPELINE RUNS (Audit Log)
-- ═══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id       TEXT PRIMARY KEY,
    run_type     TEXT,
    status       TEXT DEFAULT 'running',
    started_at   TEXT,
    completed_at TEXT,
    stats_json   TEXT,
    error_message TEXT
);

-- ═══════════════════════════════════════════════════════
-- RAG METADATA
-- ═══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS rag_documents (
    doc_id        TEXT PRIMARY KEY,
    thread_id     TEXT REFERENCES threads(thread_id),
    chunk_index   INTEGER,
    chunk_text    TEXT,
    metadata_json TEXT,
    indexed_at    TEXT DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════
-- FULL-TEXT SEARCH (FTS5) FOR HYBRID RAG
-- ═══════════════════════════════════════════════════════

CREATE VIRTUAL TABLE IF NOT EXISTS threads_fts USING fts5(
    thread_id UNINDEXED,
    subject,
    participants,
    team_name,
    channel_name,
    raw_text,
    content='threads',
    content_rowid='rowid'
);

-- Triggers to keep threads_fts updated automatically
CREATE TRIGGER IF NOT EXISTS threads_ai AFTER INSERT ON threads BEGIN
  INSERT INTO threads_fts(rowid, thread_id, subject, participants, team_name, channel_name, raw_text)
  VALUES (new.rowid, new.thread_id, new.subject, new.participants, new.team_name, new.channel_name, new.raw_text);
END;

CREATE TRIGGER IF NOT EXISTS threads_ad AFTER DELETE ON threads BEGIN
  INSERT INTO threads_fts(threads_fts, rowid, thread_id, subject, participants, team_name, channel_name, raw_text)
  VALUES('delete', old.rowid, old.thread_id, old.subject, old.participants, old.team_name, old.channel_name, old.raw_text);
END;

CREATE TRIGGER IF NOT EXISTS threads_au AFTER UPDATE ON threads BEGIN
  INSERT INTO threads_fts(threads_fts, rowid, thread_id, subject, participants, team_name, channel_name, raw_text)
  VALUES('delete', old.rowid, old.thread_id, old.subject, old.participants, old.team_name, old.channel_name, old.raw_text);
  INSERT INTO threads_fts(rowid, thread_id, subject, participants, team_name, channel_name, raw_text)
  VALUES (new.rowid, new.thread_id, new.subject, new.participants, new.team_name, new.channel_name, new.raw_text);
END;

-- Performance Indices
CREATE INDEX IF NOT EXISTS idx_threads_date ON threads(thread_date);
CREATE INDEX IF NOT EXISTS idx_events_signal_type ON events(signal_type);
CREATE INDEX IF NOT EXISTS idx_actionables_status ON actionables(status);
CREATE INDEX IF NOT EXISTS idx_dragging_issues_status ON dragging_issues(status);
CREATE INDEX IF NOT EXISTS idx_summaries_type ON summaries(summary_type);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_status ON agent_tasks(status, lane, priority DESC);
"""

# ─────────────────────────────────────────────────────────────────────
# SEED DATA
# ─────────────────────────────────────────────────────────────────────

INITIAL_SIGNAL_TYPES = [
    {"signal_type": "delay_risk", "category": "delivery", "description": "Discussion indicating a task, milestone, or deliverable may be delayed."},
    {"signal_type": "client_complaint", "category": "client_relations", "description": "Client expressing dissatisfaction, raising issues, or escalating concerns."},
    {"signal_type": "blocker", "category": "delivery", "description": "A hard blocker preventing progress on a task or project."},
    {"signal_type": "resource_gap", "category": "resource_management", "description": "Shortage of people, tools, budget, or infrastructure needed to deliver."},
    {"signal_type": "escalation", "category": "process", "description": "An issue being escalated to higher management or cross-team leadership."},
    {"signal_type": "decision_pending", "category": "process", "description": "A key decision is awaited that blocks downstream work."},
    {"signal_type": "deadline_missed", "category": "delivery", "description": "A committed deadline has been missed or is acknowledged as missed."},
    {"signal_type": "scope_creep", "category": "project_health", "description": "Requirements expanding beyond original scope without formal change control."},
    {"signal_type": "quality_issue", "category": "delivery", "description": "Bugs, defects, regressions, or quality concerns raised in discussion."},
    {"signal_type": "dependency_blocked", "category": "delivery", "description": "Work blocked due to dependency on another team, vendor, or external party."},
    {"signal_type": "morale_issue", "category": "team_dynamics", "description": "Signs of burnout, frustration, conflict, or low team morale."},
    {"signal_type": "knowledge_gap", "category": "team_dynamics", "description": "Lack of expertise or documentation causing confusion or rework."},
    {"signal_type": "process_violation", "category": "process", "description": "Deviation from established processes, SOPs, or compliance requirements."},
    {"signal_type": "positive_milestone", "category": "project_health", "description": "A milestone, release, or deliverable successfully completed."},
    {"signal_type": "client_praise", "category": "client_relations", "description": "Positive feedback or appreciation from a client or stakeholder."},
    {"signal_type": "team_alignment", "category": "team_dynamics", "description": "Evidence of strong team coordination, consensus, or effective collaboration."},
    {"signal_type": "budget_concern", "category": "resource_management", "description": "Discussion around budget overruns, cost pressures, or funding shortfalls."},
    {"signal_type": "security_concern", "category": "process", "description": "Security vulnerabilities, data handling issues, or compliance risks raised."},
    {"signal_type": "dragging_issue", "category": "delivery", "description": "An issue, client request, or task that has been stalled, unresolved, or verbally waiting over multiple days or weeks."},
]

INITIAL_CLUSTERS = [
    {"cluster_type": "project_health", "category": "delivery_execution", "description": "Overall health of project delivery — milestones, scope control, and progress tracking.", "persistence": 0.8, "decay_rate": 0.005},
    {"cluster_type": "client_relations", "category": "external_stakeholders", "description": "Client satisfaction, feedback quality, complaint trends, and relationship health.", "persistence": 0.8, "decay_rate": 0.005},
    {"cluster_type": "team_dynamics", "category": "human_capital", "description": "Team morale, collaboration quality, knowledge sharing, and internal alignment.", "persistence": 0.6, "decay_rate": 0.02},
    {"cluster_type": "delivery_risk", "category": "risk_management", "description": "Blockers, delays, dependency issues, and deadline risks threatening deliverables.", "persistence": 0.7, "decay_rate": 0.01},
    {"cluster_type": "process_compliance", "category": "governance", "description": "Adherence to processes, escalation handling, decision-making velocity, and compliance.", "persistence": 0.7, "decay_rate": 0.01},
    {"cluster_type": "resource_management", "category": "operations", "description": "Resource allocation, budget health, infrastructure capacity, and staffing adequacy.", "persistence": 0.6, "decay_rate": 0.02},
]


def init_db():
    """
    Initialize the database: create all tables and seed registries.

    Safe to call multiple times (uses CREATE TABLE IF NOT EXISTS).
    """
    with get_db() as conn:
        conn.executescript(_SCHEMA_SQL)

        # Seed signal types if empty
        count = conn.execute("SELECT COUNT(*) FROM signal_types").fetchone()[0]
        if count == 0:
            conn.executemany(
                "INSERT OR IGNORE INTO signal_types (signal_type, category, description) VALUES (?, ?, ?)",
                [(st["signal_type"], st["category"], st["description"]) for st in INITIAL_SIGNAL_TYPES]
            )

        # Seed clusters if empty
        count = conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
        if count == 0:
            conn.executemany(
                "INSERT OR IGNORE INTO clusters (cluster_type, category, description, persistence, decay_rate) VALUES (?, ?, ?, ?, ?)",
                [(cl["cluster_type"], cl["category"], cl["description"], cl["persistence"], cl["decay_rate"]) for cl in INITIAL_CLUSTERS]
            )

    logger.info("[Database] Founder Buddy database initialized successfully.")

    # Run versioned schema migrations
    try:
        from shared.migrations import run_migrations
        run_migrations()
    except Exception as me:
        logger.warning(f"[Database] Schema migration notice: {me}")


# ─────────────────────────────────────────────────────────────────────
# CONFIG HELPERS
# ─────────────────────────────────────────────────────────────────────

def get_config(key: str) -> str | None:
    """Get a config value by key. Returns None if not found."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT value, encrypted FROM app_config WHERE key = ?", (key,)
        ).fetchone()

    if row is None:
        return None

    value = row["value"]

    if row["encrypted"]:
        try:
            from shared.crypto import decryptor
            value = decryptor.decrypt(value)
        except Exception as e:
            logger.error(f"[Database] Failed to decrypt config '{key}': {e}")
            return None

    return value


def set_config(key: str, value: str, encrypt: bool = False):
    """Set a config value. Optionally encrypts it at rest."""
    stored_value = value

    if encrypt:
        try:
            from shared.crypto import decryptor
            stored_value = decryptor.encrypt(value)
        except Exception as e:
            logger.error(f"[Database] Failed to encrypt config '{key}': {e}")
            raise

    with get_db() as conn:
        conn.execute(
            """INSERT INTO app_config (key, value, encrypted, updated_at)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(key) DO UPDATE SET
                   value = excluded.value,
                   encrypted = excluded.encrypted,
                   updated_at = excluded.updated_at""",
            (key, stored_value, 1 if encrypt else 0)
        )


def get_all_config() -> dict[str, str]:
    """Get all config values as a dict. Decrypts encrypted values."""
    with get_db() as conn:
        rows = conn.execute("SELECT key, value, encrypted FROM app_config").fetchall()

    config = {}
    for row in rows:
        value = row["value"]
        if row["encrypted"]:
            try:
                from shared.crypto import decryptor
                value = decryptor.decrypt(value)
            except Exception:
                value = "***ENCRYPTED***"
        config[row["key"]] = value

    return config


def is_onboarded() -> bool:
    """Check if the initial onboarding has been completed."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM app_config WHERE key = 'onboarding_completed'"
        ).fetchone()
    return row[0] > 0


def delete_config(key: str):
    """Delete a config entry."""
    with get_db() as conn:
        conn.execute("DELETE FROM app_config WHERE key = ?", (key,))


def reset_db(preserve_config: bool = True):
    """
    Clean operational database tables.
    If preserve_config is True, app_config and excluded_channels are preserved.
    """
    with get_db() as conn:
        tables = [
            "events", "signals", "actionables", "dragging_issues",
            "summaries", "rag_documents", "pipeline_runs", "ingestion_log", "threads"
        ]
        if not preserve_config:
            tables.extend(["app_config", "excluded_channels"])

        for t in tables:
            try:
                conn.execute(f"DELETE FROM {t}")
            except Exception as e:
                logger.warning(f"[Database] Notice cleaning table {t}: {e}")

        try:
            conn.execute("INSERT INTO threads_fts(threads_fts) VALUES('rebuild')")
        except Exception:
            pass

    logger.info("[Database] Operational data tables cleaned successfully.")


def fts_search(query_str: str, limit: int = 15) -> list[dict]:
    """
    Perform FTS5 full-text keyword search across threads.
    Returns list of dict matching thread records.
    """
    if not query_str or not query_str.strip():
        return []

    import re
    clean_query = re.sub(r"[^\w\s]", " ", query_str)
    safe_terms = [f'"{t}"' for t in clean_query.split() if len(t) > 1]
    if not safe_terms:
        return []

    match_query = " OR ".join(safe_terms)

    with get_db() as conn:
        sql = """
            SELECT t.thread_id, t.source, t.subject, t.participants, t.message_count,
                   t.first_message_at, t.last_message_at, t.team_name, t.channel_name,
                   t.thread_date, t.raw_text, f.rank
            FROM threads_fts f
            JOIN threads t ON f.rowid = t.rowid
            WHERE threads_fts MATCH ?
            ORDER BY f.rank
            LIMIT ?
        """
        try:
            rows = conn.execute(sql, (match_query, limit)).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"[Database] FTS search error: {e}")
            return []

