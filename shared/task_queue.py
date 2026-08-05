"""
Asynchronous Agent Task Queue & Dispatcher.

Manages background tasks in the `agent_tasks` SQLite queue.
Supports two processing lanes:
  1. Fast Lane: High-throughput, 0 LLM call operations (cleaning, scrubbing, vector indexing).
  2. Analytics Lane: Rate-limited, deep LLM processing (Gemini signal extraction, summaries).

Supports immediate fire-and-forget task poking to trigger execution without waiting for cron ticks.
"""

from __future__ import annotations

import json
import logging
import uuid
import datetime
import asyncio
from typing import Any
from shared.database import get_db

logger = logging.getLogger(__name__)

# Callback listeners registered for task execution
_TASK_HANDLERS: dict[str, Any] = {}

# Fire-and-forget poke callbacks
_POKE_LISTENERS: list[Any] = []


def register_task_handler(kind: str, handler_func):
    """Register a handler function for a specific task kind."""
    _TASK_HANDLERS[kind] = handler_func
    logger.debug(f"[TaskQueue] Registered handler for task kind: '{kind}'")


def register_poke_listener(listener_func):
    """Register a listener callback to be notified when new tasks are poked."""
    if listener_func not in _POKE_LISTENERS:
        _POKE_LISTENERS.append(listener_func)


def enqueue_task(
    kind: str,
    payload: dict[str, Any],
    lane: str = "analytics",
    priority: int = 100
) -> str:
    """
    Enqueue a new task into `agent_tasks`.

    Returns the task_id.
    """
    task_id = f"task_{uuid.uuid4().hex[:12]}"
    payload_json = json.dumps(payload)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO agent_tasks (task_id, kind, lane, payload_json, priority, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (task_id, kind, lane, payload_json, priority, now, now)
        )

    logger.info(f"[TaskQueue] Enqueued task {task_id} (kind='{kind}', lane='{lane}', priority={priority})")
    poke_queue(lane)
    return task_id


def claim_due_tasks(lane: str = "analytics", limit: int = 10, lease_seconds: int = 300) -> list[dict[str, Any]]:
    """
    Claim due pending or expired-lease tasks for execution in a specific lane.

    Updates task status to 'processing' and sets lease_expires_at.
    Returns claimed task records.
    """
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now_str = now_dt.isoformat()
    lease_expires_str = (now_dt + datetime.timedelta(seconds=lease_seconds)).isoformat()

    with get_db() as conn:
        # Find candidates
        rows = conn.execute(
            """
            SELECT task_id, kind, lane, payload_json, priority, attempts
            FROM agent_tasks
            WHERE lane = ?
              AND (
                status = 'pending'
                OR (status = 'processing' AND lease_expires_at < ?)
              )
            ORDER BY priority DESC, created_at ASC
            LIMIT ?
            """,
            (lane, now_str, limit)
        ).fetchall()

        if not rows:
            return []

        claimed = []
        for r in rows:
            task_id = r["task_id"]
            attempts = r["attempts"] + 1
            conn.execute(
                """
                UPDATE agent_tasks
                SET status = 'processing',
                    attempts = ?,
                    lease_expires_at = ?,
                    updated_at = ?
                WHERE task_id = ?
                """,
                (attempts, lease_expires_str, now_str, task_id)
            )
            claimed.append({
                "task_id": task_id,
                "kind": r["kind"],
                "lane": r["lane"],
                "payload": json.loads(r["payload_json"]),
                "priority": r["priority"],
                "attempts": attempts
            })

    return claimed


def complete_task(task_id: str):
    """Mark a task as completed."""
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            """
            UPDATE agent_tasks
            SET status = 'completed', error_message = NULL, updated_at = ?
            WHERE task_id = ?
            """,
            (now_str, task_id)
        )
    logger.info(f"[TaskQueue] Completed task {task_id}")


def fail_task(task_id: str, error_message: str, max_retries: int = 3):
    """Mark a task as failed or retryable."""
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with get_db() as conn:
        row = conn.execute("SELECT attempts FROM agent_tasks WHERE task_id = ?", (task_id,)).fetchone()
        attempts = row["attempts"] if row else 1
        new_status = 'pending' if attempts < max_retries else 'failed'

        conn.execute(
            """
            UPDATE agent_tasks
            SET status = ?, error_message = ?, updated_at = ?
            WHERE task_id = ?
            """,
            (new_status, error_message[:500], now_str, task_id)
        )
    logger.warning(f"[TaskQueue] Task {task_id} failed (status={new_status}, attempts={attempts}): {error_message}")


def poke_queue(lane: str = "analytics"):
    """
    Fire-and-forget notification to wake up background task workers immediately.
    """
    for listener in _POKE_LISTENERS:
        try:
            if asyncio.iscoroutinefunction(listener):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(listener(lane))
                except RuntimeError:
                    pass
            else:
                listener(lane)
        except Exception as e:
            logger.debug(f"[TaskQueue] Poke listener notification failed: {e}")


def process_queue_lane(lane: str = "analytics", limit: int = 10) -> int:
    """
    Synchronously claim and execute pending tasks in a given lane.

    Returns count of tasks processed.
    """
    tasks = claim_due_tasks(lane=lane, limit=limit)
    if not tasks:
        return 0

    processed_count = 0
    for task in tasks:
        task_id = task["task_id"]
        kind = task["kind"]
        payload = task["payload"]
        handler = _TASK_HANDLERS.get(kind)

        if not handler:
            logger.error(f"[TaskQueue] No handler registered for task kind '{kind}'")
            fail_task(task_id, f"No handler registered for kind '{kind}'")
            continue

        try:
            logger.info(f"[TaskQueue] Executing task {task_id} ('{kind}')...")
            handler(payload)
            complete_task(task_id)
            processed_count += 1
        except Exception as e:
            logger.exception(f"[TaskQueue] Exception handling task {task_id}: {e}")
            fail_task(task_id, str(e))

    return processed_count
