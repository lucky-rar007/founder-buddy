"""
Dashboard Database Layer.

SQLite storage for the dashboard pipeline: threads, events, signals,
clusters, actionables, and dragging issues.

Adapted from the learning project's db_client.py pattern but redesigned
for organizational communications (Teams/Outlook).
"""

import sqlite3
import os
import logging

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# PREDEFINED ORGANIZATIONAL SIGNAL TYPES & CLUSTERS (Canonical in shared.database)
# ─────────────────────────────────────────────────────────────────────

from shared.database import INITIAL_SIGNAL_TYPES, INITIAL_CLUSTERS

# ─────────────────────────────────────────────────────────────────────
# DATABASE CONNECTION MANAGEMENT
# ─────────────────────────────────────────────────────────────────────

def get_connection():
    """Get the centralized SQLite connection from shared.database."""
    from shared.database import get_connection as shared_get_connection
    return shared_get_connection()


def init_db():
    """
    Initialize dashboard-specific tables not covered by shared/database.py.

    Tables from shared.database (threads, events, signals, actionables,
    dragging_issues, signal_types, clusters, etc.) are initialized via
    shared.database.init_db() at server startup. This function only creates
    the additional tables specific to the dashboard pipeline layer.
    """
    from shared.database import get_db

    with get_db() as conn:
        # Chat threads table for multi-session RAG memory
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_threads (
                thread_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Chat messages table for RAG conversation memory
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                text TEXT NOT NULL,
                sources_json TEXT,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (thread_id) REFERENCES chat_threads (thread_id) ON DELETE CASCADE
            )
        """)

        # Pipeline savepoints table — persisted when quota is exhausted mid-pipeline
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_savepoints (
                savepoint_id TEXT PRIMARY KEY,
                run_id TEXT,
                stage TEXT,
                batch_index INTEGER DEFAULT 0,
                exhausted_model TEXT,
                partial_events_json TEXT DEFAULT '[]',
                partial_signals_json TEXT DEFAULT '[]',
                partial_actionables_json TEXT DEFAULT '{}',
                cluster_registry_json TEXT DEFAULT '{}',
                signal_registry_json TEXT DEFAULT '{}',
                created_at TEXT,
                status TEXT DEFAULT 'paused'
            )
        """)

        # Daily Operational Audit Logbook
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                log_id TEXT PRIMARY KEY,
                log_date TEXT,
                timestamp TEXT,
                stage TEXT,
                event_type TEXT,
                entity_id TEXT,
                details_json TEXT DEFAULT '{}'
            )
        """)

        # Migration: ensure estimated_tokens column exists on threads
        try:
            conn.execute("ALTER TABLE threads ADD COLUMN estimated_tokens INTEGER DEFAULT 0")
        except Exception:
            pass  # Column already exists

        # Migration: ensure thread_date and metadata_json exist on threads
        for col_def in [
            "ALTER TABLE threads ADD COLUMN thread_date TEXT",
            "ALTER TABLE threads ADD COLUMN metadata_json TEXT",
        ]:
            try:
                conn.execute(col_def)
            except Exception:
                pass

        # Migration: ensure pipeline_run_id column exists on signals
        try:
            conn.execute("ALTER TABLE signals ADD COLUMN pipeline_run_id TEXT")
        except Exception:
            pass

        # Migration: ensure pipeline_run_id column exists on events
        try:
            conn.execute("ALTER TABLE events ADD COLUMN pipeline_run_id TEXT")
        except Exception:
            pass

    logger.info("[Database] Dashboard-specific tables initialized successfully.")


# ─────────────────────────────────────────────────────────────────────
# CRUD OPERATIONS
# ─────────────────────────────────────────────────────────────────────

# --- Signal Types ---

# --- Signal Types ---

def add_signal_type(signal_type, category, description):
    try:
        from shared.database import get_db
        with get_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO signal_types (signal_type, category, description) VALUES (?, ?, ?)",
                (signal_type, category, description)
            )
    except Exception as e:
        logger.error(f"[Database] add_signal_type failed: {e}")


def get_signal_types():
    try:
        from shared.database import get_db
        with get_db() as conn:
            rows = conn.execute("SELECT signal_type, category, description FROM signal_types").fetchall()
            return [{"signal_type": r["signal_type"], "category": r["category"], "description": r["description"]} for r in rows]
    except Exception as e:
        logger.error(f"[Database] get_signal_types failed: {e}")
        return []


# --- Clusters ---

def add_cluster(cluster_type, category, description, persistence=0.6, decay_rate=0.02):
    try:
        from shared.database import get_db
        with get_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO clusters (cluster_type, category, description, persistence, decay_rate) VALUES (?, ?, ?, ?, ?)",
                (cluster_type, category, description, persistence, decay_rate)
            )
    except Exception as e:
        logger.error(f"[Database] add_cluster failed: {e}")


def get_clusters():
    try:
        from shared.database import get_db
        with get_db() as conn:
            rows = conn.execute("SELECT cluster_type, category, description, persistence, decay_rate FROM clusters").fetchall()
            return [{"cluster_type": r["cluster_type"], "category": r["category"], "description": r["description"], "persistence": r["persistence"], "decay_rate": r["decay_rate"]} for r in rows]
    except Exception as e:
        logger.error(f"[Database] get_clusters failed: {e}")
        return []


# --- Threads ---

def add_thread(thread):
    try:
        from shared.database import get_db
        with get_db() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO threads
                (thread_id, source, source_id, subject, participants, message_count,
                 first_message_at, last_message_at, raw_text, team_name, channel_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    thread.get("thread_id"), thread.get("source"), thread.get("source_id"),
                    thread.get("subject"), thread.get("participants"), thread.get("message_count"),
                    thread.get("first_message_at"), thread.get("last_message_at"),
                    thread.get("raw_text"), thread.get("team_name"), thread.get("channel_name")
                )
            )
    except Exception as e:
        logger.error(f"[Database] add_thread failed: {e}")


def get_threads(limit_days: int | None = None):
    try:
        from shared.database import get_db
        with get_db() as conn:
            if limit_days:
                from datetime import datetime, timedelta
                cutoff_date = (datetime.now() - timedelta(days=limit_days)).strftime("%Y-%m-%d")
                rows = conn.execute("""SELECT thread_id, source, source_id, subject, participants,
                                 message_count, first_message_at, last_message_at, raw_text,
                                 team_name, channel_name, thread_date FROM threads WHERE thread_date >= ?""", (cutoff_date,)).fetchall()
            else:
                rows = conn.execute("""SELECT thread_id, source, source_id, subject, participants,
                                 message_count, first_message_at, last_message_at, raw_text,
                                 team_name, channel_name, thread_date FROM threads""").fetchall()
            return [{
                "thread_id": r["thread_id"], "source": r["source"], "source_id": r["source_id"],
                "subject": r["subject"], "participants": r["participants"], "message_count": r["message_count"],
                "first_message_at": r["first_message_at"], "last_message_at": r["last_message_at"],
                "raw_text": r["raw_text"], "team_name": r["team_name"], "channel_name": r["channel_name"],
                "thread_date": r["thread_date"]
            } for r in rows]
    except Exception as e:
        logger.error(f"[Database] get_threads failed: {e}")
        return []


# --- Events ---

def add_event(event):
    try:
        from shared.database import get_db
        with get_db() as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute(
                """INSERT OR REPLACE INTO events
                (event_id, thread_id, signal_type, impact_area, direction, confidence, summary, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.get("event_id"), event.get("thread_id"), event.get("signal_type"),
                    event.get("impact_area"), event.get("direction"), event.get("confidence"),
                    event.get("summary"), event.get("timestamp")
                )
            )
            conn.execute("PRAGMA foreign_keys=ON")
    except Exception as e:
        logger.error(f"[Database] add_event failed: {e}")


def get_events():
    try:
        from shared.database import get_db
        with get_db() as conn:
            rows = conn.execute("SELECT event_id, thread_id, signal_type, impact_area, direction, confidence, summary, timestamp FROM events").fetchall()
            return [{
                "event_id": r["event_id"], "thread_id": r["thread_id"], "signal_type": r["signal_type"],
                "impact_area": r["impact_area"], "direction": r["direction"], "confidence": r["confidence"],
                "summary": r["summary"], "timestamp": r["timestamp"]
            } for r in rows]
    except Exception as e:
        logger.error(f"[Database] get_events failed: {e}")
        return []


# --- Signals ---

def add_signal(signal):
    try:
        from shared.database import get_db
        with get_db() as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute(
                """INSERT OR REPLACE INTO signals
                (signal_id, event_id, thread_id, signal_type, cluster_type,
                 strength, decayed_strength, persistence, decay_rate,
                 relevance_score, confidence, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    signal.get("signal_id"), signal.get("event_id"), signal.get("thread_id"),
                    signal.get("signal_type"), signal.get("cluster_type"),
                    signal.get("strength"), signal.get("decayed_strength"),
                    signal.get("persistence"), signal.get("decay_rate"),
                    signal.get("relevance_score"), signal.get("confidence"),
                    signal.get("timestamp")
                )
            )
            conn.execute("PRAGMA foreign_keys=ON")
    except Exception as e:
        logger.error(f"[Database] add_signal failed: {e}")


def get_signals():
    try:
        from shared.database import get_db
        with get_db() as conn:
            rows = conn.execute("""SELECT signal_id, event_id, thread_id, signal_type, cluster_type,
                             strength, decayed_strength, persistence, decay_rate,
                             relevance_score, confidence, timestamp FROM signals""").fetchall()
            return [{
                "signal_id": r["signal_id"], "event_id": r["event_id"], "thread_id": r["thread_id"],
                "signal_type": r["signal_type"], "cluster_type": r["cluster_type"],
                "strength": r["strength"], "decayed_strength": r["decayed_strength"],
                "persistence": r["persistence"], "decay_rate": r["decay_rate"],
                "relevance_score": r["relevance_score"], "confidence": r["confidence"],
                "timestamp": r["timestamp"]
            } for r in rows]
    except Exception as e:
        logger.error(f"[Database] get_signals failed: {e}")
        return []


# --- Actionables ---

def add_actionable(actionable):
    try:
        from shared.database import get_db
        with get_db() as conn:
            # Temporarily disable FK enforcement — the pipeline may generate
            # actionables referencing thread/event IDs that were inserted in
            # a different batch or connection context.
            conn.execute("PRAGMA foreign_keys=OFF")

            # Check if an actionable with the same thread_id and title already exists
            # to preserve user-updated status (e.g. in_progress, resolved, dismissed)
            existing = conn.execute(
                "SELECT actionable_id, status FROM actionables WHERE thread_id = ? AND title = ?",
                (actionable.get("thread_id"), actionable.get("title"))
            ).fetchone()

            act_id = existing[0] if existing else actionable.get("actionable_id")
            status = existing[1] if existing else actionable.get("status", "open")

            conn.execute(
                """INSERT OR REPLACE INTO actionables
                (actionable_id, thread_id, event_id, title, description, priority, status, source, created_at, due_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    act_id, actionable.get("thread_id"),
                    actionable.get("event_id"), actionable.get("title"),
                    actionable.get("description"), actionable.get("priority"),
                    status, actionable.get("source"),
                    actionable.get("created_at"), actionable.get("due_date")
                )
            )

            # Re-enable FK enforcement for subsequent operations
            conn.execute("PRAGMA foreign_keys=ON")
    except Exception as e:
        logger.error(f"[Database] add_actionable failed: {e}")


def get_actionables():
    try:
        from shared.database import get_db
        with get_db() as conn:
            rows = conn.execute(
                """SELECT actionable_id, thread_id, event_id, title, description,
                          priority, status, source, created_at, due_date FROM actionables"""
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"[Database] get_actionables failed: {e}")
        return []


# --- Dragging Issues ---

def add_dragging_issue(issue):
    try:
        from shared.database import get_db
        with get_db() as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute(
                """INSERT OR REPLACE INTO dragging_issues
                (issue_id, thread_id, signal_id, title, description, days_unresolved, severity, first_detected_at, last_checked_at, recheck_after, recheck_reason, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    issue.get("issue_id"), issue.get("thread_id"),
                    issue.get("signal_id"), issue.get("title"),
                    issue.get("description"), issue.get("days_unresolved"),
                    issue.get("severity"), issue.get("first_detected_at"),
                    issue.get("last_checked_at"), issue.get("recheck_after"),
                    issue.get("recheck_reason"), issue.get("status", "active")
                )
            )
            conn.execute("PRAGMA foreign_keys=ON")
    except Exception as e:
        logger.error(f"[Database] add_dragging_issue failed: {e}")


def get_dragging_issues():
    try:
        from shared.database import get_db
        with get_db() as conn:
            rows = conn.execute(
                """SELECT issue_id, thread_id, signal_id, title, description,
                          days_unresolved, severity, first_detected_at, last_checked_at, recheck_after, recheck_reason, status
                   FROM dragging_issues WHERE status = 'active'"""
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"[Database] get_dragging_issues failed: {e}")
        return []


# --- Utilities ---

def clear_pipeline_data():
    """Clear all pipeline-generated data while preserving registries."""
    try:
        from shared.database import get_db
        with get_db() as conn:
            conn.execute("DELETE FROM dragging_issues")
            conn.execute("DELETE FROM actionables")
            conn.execute("DELETE FROM signals")
            conn.execute("DELETE FROM events")
            conn.execute("DELETE FROM threads")
        logger.info("[Database] Successfully cleared all pipeline data.")
        return True
    except Exception as e:
        logger.error(f"[Database] clear_pipeline_data failed: {e}")
        return False


def get_pipeline_stats():
    """Return summary stats of the current pipeline state."""
    try:
        from shared.database import get_db
        with get_db() as conn:
            stats = {}
            for table in ["threads", "events", "signals", "actionables", "dragging_issues"]:
                row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                stats[table] = row[0]
            return stats
    except Exception as e:
        logger.error(f"[Database] get_pipeline_stats failed: {e}")
        return {}


# ─── Summaries & Pipeline Runs ───────────────────────────────

def add_summary(summary: dict) -> bool:
    try:
        from shared.database import get_db
        with get_db() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO summaries
                   (summary_id, summary_type, period_start, period_end, title, content_json, content_markdown, stats_json, generated_at, pipeline_run_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)""",
                (
                    summary.get("summary_id"), summary.get("summary_type"),
                    summary.get("period_start"), summary.get("period_end"),
                    summary.get("title"), summary.get("content_json"),
                    summary.get("content_markdown"), summary.get("stats_json"),
                    summary.get("pipeline_run_id")
                )
            )
        return True
    except Exception as e:
        logger.error(f"[Database] add_summary failed: {e}")
        return False


def get_summary(summary_type: str, period_start: str, period_end: str) -> dict | None:
    try:
        from shared.database import get_db
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM summaries WHERE summary_type = ? AND period_start = ? AND period_end = ?",
                (summary_type, period_start, period_end)
            ).fetchone()
            if row:
                return dict(row)
            return None
    except Exception as e:
        logger.error(f"[Database] get_summary failed: {e}")
        return None


def get_available_summaries(summary_type: str) -> list[dict]:
    try:
        from shared.database import get_db
        with get_db() as conn:
            rows = conn.execute(
                "SELECT period_start, period_end, title, generated_at FROM summaries WHERE summary_type = ? ORDER BY period_start DESC",
                (summary_type,)
            ).fetchall()
            summaries_list = [dict(r) for r in rows]

        if not summaries_list:
            from dashboard.summaries import SummaryEngine
            engine = SummaryEngine()
            engine.update_all_active_summaries()

            with get_db() as conn:
                rows = conn.execute(
                    "SELECT period_start, period_end, title, generated_at FROM summaries WHERE summary_type = ? ORDER BY period_start DESC",
                    (summary_type,)
                ).fetchall()
                summaries_list = [dict(r) for r in rows]

        return summaries_list
    except Exception as e:
        logger.error(f"[Database] get_available_summaries failed: {e}")
        return []


def add_pipeline_run(run: dict) -> bool:
    try:
        from shared.database import get_db
        with get_db() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO pipeline_runs
                   (run_id, run_type, status, started_at, completed_at, stats_json, error_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.get("run_id"), run.get("run_type"), run.get("status"),
                    run.get("started_at"), run.get("completed_at"),
                    run.get("stats_json"), run.get("error_message")
                )
            )
        return True
    except Exception as e:
        logger.error(f"[Database] add_pipeline_run failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────
# SAVEPOINT CRUD — Pipeline Quota Pause/Resume
# ─────────────────────────────────────────────────────────────────────

def save_savepoint(savepoint: dict) -> bool:
    """Persist a pipeline savepoint when quota is exhausted mid-pipeline."""
    try:
        from shared.database import get_db
        with get_db() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO pipeline_savepoints
                   (savepoint_id, run_id, stage, batch_index, exhausted_model,
                    partial_events_json, partial_signals_json, partial_actionables_json,
                    cluster_registry_json, signal_registry_json, created_at, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    savepoint.get("savepoint_id"),
                    savepoint.get("run_id"),
                    savepoint.get("stage"),
                    savepoint.get("batch_index", 0),
                    savepoint.get("exhausted_model", ""),
                    savepoint.get("partial_events_json", "[]"),
                    savepoint.get("partial_signals_json", "[]"),
                    savepoint.get("partial_actionables_json", "[]"),
                    savepoint.get("cluster_registry_json", "{}"),
                    savepoint.get("signal_registry_json", "{}"),
                    savepoint.get("created_at", ""),
                    savepoint.get("status", "paused"),
                )
            )
        return True
    except Exception as e:
        logger.error(f"[Database] save_savepoint failed: {e}")
        return False


def get_latest_savepoint() -> dict | None:
    """Returns the most recent paused savepoint, or None if no paused savepoints exist."""
    try:
        from shared.database import get_db
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM pipeline_savepoints WHERE status = 'paused' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"[Database] get_latest_savepoint failed: {e}")
        return None


def mark_savepoint_resumed(savepoint_id: str) -> bool:
    """Marks a savepoint as resumed so it no longer shows the Resume banner."""
    try:
        from shared.database import get_db
        with get_db() as conn:
            conn.execute(
                "UPDATE pipeline_savepoints SET status = 'resumed' WHERE savepoint_id = ?",
                (savepoint_id,)
            )
        return True
    except Exception as e:
        logger.error(f"[Database] mark_savepoint_resumed failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────
# AUDIT LOGBOOK & LAST ACTIVE DATE HELPERS
# ─────────────────────────────────────────────────────────────────────

def add_audit_log(
    log_date: str,
    stage: str,
    event_type: str,
    entity_id: str = "",
    details: dict | None = None
) -> bool:
    """
    Inserts a trace entry into the daily operational audit logbook.
    """
    import json
    import uuid
    from datetime import datetime

    try:
        from shared.database import get_db
        log_id = f"log_{str(uuid.uuid4())[:8]}"
        ts = datetime.now().isoformat()
        details_json = json.dumps(details or {})

        with get_db() as conn:
            conn.execute(
                """INSERT INTO audit_logs
                   (log_id, log_date, timestamp, stage, event_type, entity_id, details_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (log_id, log_date, ts, stage, event_type, entity_id, details_json)
            )
        return True
    except Exception as e:
        logger.error(f"[Database] add_audit_log failed: {e}")
        return False


def get_audit_logs(date_str: str | None = None, limit: int = 100) -> list[dict]:
    """
    Retrieves audit logs for a specific date (or all recent logs if date_str is None).
    """
    import json

    try:
        from shared.database import get_db
        with get_db() as conn:
            if date_str:
                rows = conn.execute(
                    """SELECT * FROM audit_logs
                       WHERE log_date = ?
                       ORDER BY timestamp ASC
                       LIMIT ?""",
                    (date_str, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM audit_logs
                       ORDER BY timestamp DESC
                       LIMIT ?""",
                    (limit,)
                ).fetchall()

            results = []
            for r in rows:
                item = dict(r)
                try:
                    item["details"] = json.loads(item.get("details_json", "{}"))
                except Exception:
                    item["details"] = {}
                results.append(item)
            return results
    except Exception as e:
        logger.error(f"[Database] get_audit_logs failed: {e}")
        return []


def get_last_active_date() -> str | None:
    """
    Returns the most recent YYYY-MM-DD string with recorded conversation threads in the database.
    Used for last-active-day dashboard fallback when today has no messages.
    """
    try:
        from shared.database import get_db
        with get_db() as conn:
            row = conn.execute(
                """SELECT thread_date FROM threads
                   WHERE thread_date IS NOT NULL AND thread_date != ''
                   ORDER BY thread_date DESC
                   LIMIT 1"""
            ).fetchone()
            if row and row[0]:
                return row[0]

            # Fallback: check first_message_at timestamp substring
            row2 = conn.execute(
                """SELECT SUBSTR(first_message_at, 1, 10) as f_date FROM threads
                   WHERE first_message_at IS NOT NULL AND LENGTH(first_message_at) >= 10
                   ORDER BY first_message_at DESC
                   LIMIT 1"""
            ).fetchone()
            return row2[0] if row2 else None
    except Exception as e:
        logger.error(f"[Database] get_last_active_date failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────
# RAG MULTI-SESSION CHAT THREAD CRUD HELPERS
# ─────────────────────────────────────────────────────────────────────

def create_chat_thread(title: str = "New Chat") -> dict:
    """Create a new chat session thread in SQLite."""
    import time
    from shared.database import get_db
    thread_id = f"chat_{int(time.time() * 1000)}"
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO chat_threads (thread_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (thread_id, title, now, now)
        )
    return {"thread_id": thread_id, "title": title, "created_at": now, "updated_at": now}


def get_chat_threads() -> list[dict]:
    """Retrieve all chat sessions sorted by updated_at descending."""
    from shared.database import get_db
    with get_db() as conn:
        rows = conn.execute(
            "SELECT thread_id, title, created_at, updated_at FROM chat_threads ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def delete_chat_thread(thread_id: str) -> bool:
    """Delete a chat session and all its stored messages."""
    from shared.database import get_db
    with get_db() as conn:
        conn.execute("DELETE FROM chat_messages WHERE thread_id = ?", (thread_id,))
        conn.execute("DELETE FROM chat_threads WHERE thread_id = ?", (thread_id,))
    return True


def add_chat_message(thread_id: str, sender: str, text: str, sources: list | None = None) -> dict:
    """Append a message turn to a chat thread and update thread timestamp."""
    import time
    import json
    from shared.database import get_db
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    sources_json = json.dumps(sources or [])
    with get_db() as conn:
        # Check thread exists; create if missing
        row = conn.execute("SELECT title FROM chat_threads WHERE thread_id = ?", (thread_id,)).fetchone()
        if not row:
            title_snippet = text[:36] + ("..." if len(text) > 36 else "")
            conn.execute(
                "INSERT INTO chat_threads (thread_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (thread_id, title_snippet, now, now)
            )
        else:
            conn.execute("UPDATE chat_threads SET updated_at = ? WHERE thread_id = ?", (now, thread_id))

        cur = conn.execute(
            """INSERT INTO chat_messages (thread_id, sender, text, sources_json, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (thread_id, sender, text, sources_json, now)
        )
        msg_id = cur.lastrowid

    return {
        "id": msg_id,
        "thread_id": thread_id,
        "sender": sender,
        "text": text,
        "sources": sources or [],
        "timestamp": now
    }


def get_chat_messages(thread_id: str) -> list[dict]:
    """Retrieve all messages for a specific chat thread."""
    import json
    from shared.database import get_db
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, thread_id, sender, text, sources_json, timestamp
               FROM chat_messages WHERE thread_id = ? ORDER BY id ASC""",
            (thread_id,)
        ).fetchall()
        results = []
        for r in rows:
            item = dict(r)
            try:
                item["sources"] = json.loads(item.get("sources_json") or "[]")
            except Exception:
                item["sources"] = []
            item.pop("sources_json", None)
            results.append(item)
        return results


def update_chat_thread_title(thread_id: str, title: str):
    """Update the display title of a chat thread."""
    from shared.database import get_db
    with get_db() as conn:
        conn.execute("UPDATE chat_threads SET title = ? WHERE thread_id = ?", (title, thread_id))


