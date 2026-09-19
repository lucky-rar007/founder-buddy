"""
Dashboard Pipeline Savepoints.

Handles creating and resuming pipeline savepoints when quota exhaustion
or interruptions occur during processing batches.
"""

from __future__ import annotations

import os
import uuid
import json
import logging
from datetime import datetime

from dashboard.decay import detect_dragging_issues

logger = logging.getLogger(__name__)


def create_savepoint(
    run_id: str,
    stage: str,
    batch_index: int,
    exhausted_model: str,
    partial_events: list,
    partial_signals: list,
    partial_actionables: list,
    cluster_registry: dict,
    signal_registry: dict
) -> str:
    """Persists a pipeline savepoint to SQLite and returns the savepoint_id."""
    from dashboard.db import save_savepoint
    savepoint_id = f"sp_{str(uuid.uuid4())[:8]}"
    save_savepoint({
        "savepoint_id": savepoint_id,
        "run_id": run_id,
        "stage": stage,
        "batch_index": batch_index,
        "exhausted_model": exhausted_model,
        "partial_events_json": json.dumps(partial_events),
        "partial_signals_json": json.dumps(partial_signals),
        "partial_actionables_json": json.dumps(partial_actionables),
        "cluster_registry_json": json.dumps(cluster_registry),
        "signal_registry_json": json.dumps(signal_registry),
        "created_at": datetime.now().isoformat(),
        "status": "paused"
    })
    logger.info(f"[Pipeline] Savepoint '{savepoint_id}' created at stage='{stage}', batch={batch_index}.")
    return savepoint_id


# Backward compatibility alias
_create_savepoint = create_savepoint


def resume_pipeline_from_savepoint(savepoint_id: str, api_key: str | None = None) -> dict:
    """
    Resumes a paused pipeline from a persisted savepoint.
    Re-runs only the remaining unprocessed batches from the saved batch_index onward.
    """
    from dashboard.db import (
        get_latest_savepoint, mark_savepoint_resumed, save_savepoint,
        add_event, add_signal, add_actionable, add_dragging_issue, add_pipeline_run, get_threads
    )
    from dashboard.pipeline import (
        run_event_extraction, run_signal_clustering, run_cluster_health_evaluation
    )

    if not api_key:
        api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        from shared.database import get_config
        api_key = get_config("gemini_api_key")

    # Load the specific savepoint by ID
    from shared.database import get_db_read
    with get_db_read() as conn:
        row = conn.execute(
            "SELECT * FROM pipeline_savepoints WHERE savepoint_id = ?", (savepoint_id,)
        ).fetchone()

    if not row:
        raise ValueError(f"Savepoint '{savepoint_id}' not found.")

    sp = dict(row)
    stage = sp["stage"]
    batch_index = sp["batch_index"]
    partial_events = json.loads(sp["partial_events_json"] or "[]")
    partial_signals = json.loads(sp["partial_signals_json"] or "[]")
    partial_actionables = json.loads(sp["partial_actionables_json"] or "[]")
    cluster_registry = json.loads(sp["cluster_registry_json"] or "{}")
    signal_registry = json.loads(sp["signal_registry_json"] or "{}")
    run_id = sp["run_id"] or f"run_{str(uuid.uuid4())[:8]}_resume"

    logger.info(f"\n[Pipeline] Resuming from savepoint '{savepoint_id}' at stage='{stage}', batch={batch_index}")

    all_threads = [dict(t) for t in get_threads(limit_days=30)]

    # Resume event extraction from the saved batch_index
    if stage == "event_extraction":
        remaining_threads = all_threads[batch_index * 5:]  # default batch_size=5
        new_events, new_actionables = run_event_extraction(
            threads=remaining_threads,
            api_key=api_key,
            signal_registry=signal_registry
        )
        partial_events.extend(new_events)
        partial_actionables.extend(new_actionables)

    # Run (or resume) signal clustering
    if stage in ("event_extraction", "signal_clustering"):
        remaining_events = partial_events[batch_index * 30:] if stage == "signal_clustering" else partial_events
        new_signals, cluster_registry = run_signal_clustering(
            events=remaining_events if stage == "signal_clustering" else partial_events,
            api_key=api_key,
            cluster_registry=cluster_registry
        )
        partial_signals.extend(new_signals)

    # Cluster health evaluation
    dashboard_clusters = run_cluster_health_evaluation(
        signals=partial_signals,
        api_key=api_key,
        cluster_registry=cluster_registry
    )

    # Persist results
    for ev in partial_events:
        add_event(ev)
    for sig in partial_signals:
        add_signal(sig)
    for act in partial_actionables:
        add_actionable(act)

    dragging_issues = detect_dragging_issues(partial_signals)
    for drag in dragging_issues:
        drag_record = {
            "issue_id": f"drag_{str(uuid.uuid4())[:8]}",
            "thread_id": drag.get("thread_id", ""),
            "signal_id": drag.get("signal_id", ""),
            "title": f"{drag.get('signal_type', 'Unknown').replace('_', ' ').title()} — Unresolved",
            "description": drag.get("summary", ""),
            "days_unresolved": drag.get("days_unresolved", 0),
            "severity": drag.get("severity", "medium"),
            "first_detected_at": drag.get("timestamp", ""),
            "last_checked_at": datetime.now().isoformat(),
            "status": "active"
        }
        add_dragging_issue(drag_record)

    mark_savepoint_resumed(savepoint_id)

    add_pipeline_run({
        "run_id": run_id,
        "run_type": "resume",
        "status": "completed",
        "started_at": datetime.now().isoformat(),
        "completed_at": datetime.now().isoformat(),
        "stats_json": json.dumps({
            "events": len(partial_events),
            "signals": len(partial_signals),
            "actionables": len(partial_actionables)
        })
    })

    return {
        "paused": False,
        "threads": all_threads,
        "events": partial_events,
        "signals": partial_signals,
        "actionables": partial_actionables,
        "clusters": dashboard_clusters,
        "dragging_issues": dragging_issues,
        "stats": {
            "threads": len(all_threads),
            "events": len(partial_events),
            "signals": len(partial_signals),
            "actionables": len(partial_actionables),
            "dragging_issues": len(dragging_issues)
        }
    }
