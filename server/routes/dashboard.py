"""
Dashboard API Routes.

Handles retrieval of Daily/Weekly/Monthly summaries, lists generated periods,
exposes dashboard metrics, and triggers pipeline execution.
"""

from __future__ import annotations

import logging
import asyncio
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from shared.database import get_db, get_config
from dashboard.db import (
    get_summary, get_available_summaries, get_pipeline_stats,
    get_latest_savepoint, get_audit_logs, get_last_active_date
)
from dashboard.pipeline import run_full_pipeline, resume_pipeline_from_savepoint
from dashboard.summaries import SummaryEngine
from shared.model_router import router as model_router

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────
# API ENDPOINTS
# ─────────────────────────────────────────────────────────────────────

@router.get("/summary")
async def get_dashboard_summary(
    type: str,
    start: str,
    end: str
):
    """
    Get a specific daily, weekly, or monthly summary scorecard.
    If a daily summary is missing, attempt to compile it dynamically.
    """
    try:
        summary = get_summary(type, start, end)
        is_fallback = False
        fallback_date = None
        api_key = get_config("gemini_api_key")

        if not summary:
            engine = SummaryEngine(api_key=api_key)
            if type == "daily":
                summary = engine.generate_daily_summary(start)
            elif type == "weekly":
                summary = engine.generate_weekly_summary(start, end)
            elif type == "monthly":
                summary = engine.generate_monthly_summary(start, end)

        # Fallback to last active date if requested date has no data
        if not summary and type == "daily":
            last_date = get_last_active_date()
            if last_date and last_date != start:
                summary = get_summary("daily", last_date, last_date)
                if not summary:
                    engine = SummaryEngine(api_key=api_key)
                    summary = engine.generate_daily_summary(last_date)
                if summary:
                    is_fallback = True
                    fallback_date = last_date

        if not summary:
            raise HTTPException(
                status_code=404,
                detail=f"No {type} summary found for the period {start} to {end}."
            )

        # Parse JSON fields for frontend ease of access
        import json
        res = dict(summary)
        try:
            res["content_json"] = json.loads(res["content_json"])
        except Exception:
            pass
        try:
            res["stats_json"] = json.loads(res["stats_json"])
        except Exception:
            pass

        return {
            "success": True,
            "summary": res,
            "is_fallback": is_fallback,
            "fallback_date": fallback_date
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"[API] Summary lookup failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary/available")
async def get_available_periods(type: str):
    """
    Retrieve list of generated scorecard periods to populate the UI select selector.
    """
    try:
        periods = get_available_summaries(type)
        return {"success": True, "periods": periods}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_dashboard_stats(limit: int = 100):
    """
    Get summary metrics (counts of issues, event counts, active dragging items).
    Supports limiting total actionables returned (default 100).
    """
    try:
        stats = get_pipeline_stats()
        
        # Load active dragging issues list (top 50)
        dragging = []
        with get_db() as conn:
            rows = conn.execute(
                """SELECT * FROM dragging_issues 
                   WHERE status IN ('active', 'open', 'in_progress') 
                   ORDER BY days_unresolved DESC LIMIT 50"""
            ).fetchall()
            dragging = [dict(r) for r in rows]

        # Collect set of dragging identifiers/titles for strict mutual exclusivity
        dragging_thread_ids = {d.get("thread_id") for d in dragging if d.get("thread_id")}
        dragging_titles = {d.get("title", "").strip().lower() for d in dragging if d.get("title")}

        # Load actionables (capped at limit), excluding items present in dragging_issues
        raw_actionables = []
        with get_db() as conn:
            rows = conn.execute(
                """SELECT a.*, COALESCE(NULLIF(a.source, 'unknown'), t.source, 'teams') AS source
                   FROM actionables a
                   LEFT JOIN threads t ON a.thread_id = t.thread_id
                   ORDER BY a.created_at DESC LIMIT ?""", (min(limit, 500),)
            ).fetchall()
            raw_actionables = [dict(r) for r in rows]

        # Filter actionables to ensure zero commonality with dragging issues
        actionables = []
        for act in raw_actionables:
            act_title = (act.get("title") or "").strip().lower()
            act_thread = act.get("thread_id")
            act_id = act.get("actionable_id")

            # Check if matching dragging issue exists
            is_dragging = (
                (act_thread and act_thread in dragging_thread_ids) or
                (act_title and act_title in dragging_titles) or
                any(d.get("issue_id") == act_id for d in dragging)
            )

            if not is_dragging:
                actionables.append(act)

        last_active = get_last_active_date()

        return {
            "success": True,
            "stats": stats,
            "last_active_date": last_active,
            "dragging_issues": dragging,
            "actionables": actionables
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pipeline/run")
async def trigger_pipeline(background_tasks: BackgroundTasks):
    """
    Explicitly trigger event extraction and signal clustering pipeline
    to process any newly ingested Teams or Outlook logs via agent_tasks queue.
    """
    api_key = get_config("gemini_api_key")
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="Gemini API Key is not configured. Go to Settings or Complete Onboarding."
        )

    # Check if a pipeline run is already in progress
    with get_db() as conn:
        active_run = conn.execute(
            "SELECT run_id FROM pipeline_runs WHERE status = 'running'"
        ).fetchone()

    if active_run:
        return {
            "success": False,
            "message": "A pipeline run is already in progress in the background.",
            "run_id": active_run[0]
        }

    from shared.task_queue import enqueue_task
    task_id = enqueue_task("extract_signals", {"reason": "manual_trigger"}, lane="analytics", priority=200)

    return {
        "success": True,
        "message": f"Pipeline run enqueued (task_id: {task_id}). Worker poked for instant execution.",
        "task_id": task_id
    }


@router.get("/pipeline/savepoint")
async def get_pipeline_savepoint():
    """
    Returns the latest paused savepoint if one exists.
    Used by the frontend to show the 'Resume Pipeline' banner.
    """
    savepoint = get_latest_savepoint()
    if not savepoint:
        return {"has_savepoint": False, "savepoint": None}
    return {"has_savepoint": True, "savepoint": savepoint}


class ResumeRequest(BaseModel):
    savepoint_id: str


@router.post("/pipeline/resume")
async def resume_pipeline(req: ResumeRequest, background_tasks: BackgroundTasks):
    """
    Resumes a paused pipeline from a saved savepoint.
    Runs in background so the HTTP worker is not blocked.
    """
    api_key = get_config("gemini_api_key")
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="Gemini API key is not configured. Please complete onboarding first."
        )

    savepoint = get_latest_savepoint()
    if not savepoint or savepoint.get("savepoint_id") != req.savepoint_id:
        raise HTTPException(status_code=404, detail="Savepoint not found or already resumed.")

    def execute_resume():
        try:
            resume_pipeline_from_savepoint(req.savepoint_id, api_key=api_key)
            logging.info(f"[API] Pipeline resume from savepoint '{req.savepoint_id}' completed.")
        except Exception as e:
            logging.error(f"[API Background Task] Pipeline resume failed: {e}")

    background_tasks.add_task(execute_resume)
    return {"success": True, "message": f"Pipeline resume from savepoint '{req.savepoint_id}' triggered."}


@router.get("/pipeline/quota")
async def get_quota_status():
    """
    Returns current daily API quota usage for all models.
    Displayed in the dashboard Settings / status panel.
    """
    return {"success": True, "quota": model_router.get_quota_status()}


@router.get("/audit-logs")
async def get_dashboard_audit_logs(date: Optional[str] = None, limit: int = 100):
    """
    Retrieves daily operational audit logbook entries for the given date.
    """
    try:
        logs = get_audit_logs(date_str=date, limit=limit)
        return {"success": True, "logs": logs, "date": date or "all"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



class ActionableStatusRequest(BaseModel):
    actionable_id: str
    status: str


@router.post("/actionable/status")
async def update_actionable_status(req: ActionableStatusRequest):
    """
    Update the status of a specific actionable task.
    Supports Open, In Progress, Resolved, Dismissed column transitions.
    """
    if req.status not in ["open", "in_progress", "resolved", "dismissed"]:
        raise HTTPException(status_code=400, detail="Invalid actionable status.")

    try:
        resolved_at = datetime.now().isoformat() if req.status == "resolved" else None
        with get_db() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "UPDATE actionables SET status = ?, resolved_at = ? WHERE actionable_id = ?",
                    (req.status, resolved_at, req.actionable_id)
                )
            except Exception as sql_err:
                if "resolved_at" in str(sql_err).lower():
                    cursor.execute("ALTER TABLE actionables ADD COLUMN resolved_at TEXT")
                    cursor.execute(
                        "UPDATE actionables SET status = ?, resolved_at = ? WHERE actionable_id = ?",
                        (req.status, resolved_at, req.actionable_id)
                    )
                else:
                    raise sql_err

            if cursor.rowcount == 0:
                cursor.execute(
                    "UPDATE dragging_issues SET status = ? WHERE issue_id = ?",
                    (req.status, req.actionable_id)
                )

            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Actionable task or dragging issue not found.")
            conn.commit()

        return {"success": True, "message": f"Actionable '{req.actionable_id}' status updated to '{req.status}'."}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"[API] Actionable status update failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ActionableSeverityRequest(BaseModel):
    actionable_id: str
    severity: str


@router.post("/actionable/severity")
async def update_actionable_severity(req: ActionableSeverityRequest):
    """
    Update the severity / priority of a specific actionable task or dragging issue.
    Supports low, medium, high, critical.
    """
    sev = req.severity.lower().strip()
    if sev not in ["low", "medium", "high", "critical", "blocker"]:
        raise HTTPException(status_code=400, detail="Invalid severity level.")

    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE actionables SET priority = ? WHERE actionable_id = ?",
                (sev, req.actionable_id)
            )
            count1 = cursor.rowcount

            cursor.execute(
                "UPDATE dragging_issues SET severity = ? WHERE issue_id = ?",
                (sev, req.actionable_id)
            )
            count2 = cursor.rowcount

            if count1 == 0 and count2 == 0:
                raise HTTPException(status_code=404, detail="Item not found.")
            conn.commit()

        return {"success": True, "message": f"Severity updated to '{sev.upper()}'."}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"[API] Severity update failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ActionableDeleteRequest(BaseModel):
    actionable_id: str


@router.post("/actionable/delete")
async def delete_actionable_item(req: ActionableDeleteRequest):
    """
    Permanently delete an actionable task or dragging issue from the database.
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM actionables WHERE actionable_id = ?", (req.actionable_id,))
            c1 = cursor.rowcount
            cursor.execute("DELETE FROM dragging_issues WHERE issue_id = ?", (req.actionable_id,))
            c2 = cursor.rowcount

            if c1 == 0 and c2 == 0:
                raise HTTPException(status_code=404, detail="Item not found.")
            conn.commit()

        return {"success": True, "message": "Item permanently deleted."}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"[API] Delete failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/actionable/trace/{actionable_id}")
async def get_actionable_trace(actionable_id: str):
    """
    Get full actionable item metadata, status options, and trace to raw source communication thread.
    Parses thread raw_text into structured message bubbles for real chat UI rendering.
    """
    import re

    with get_db() as conn:
        cursor = conn.cursor()
        act_row = cursor.execute("SELECT * FROM actionables WHERE actionable_id = ?", (actionable_id,)).fetchone()
        if not act_row:
            act_row = cursor.execute(
                "SELECT issue_id as actionable_id, title, description, severity as priority, status, 'teams' as source, first_detected_at as created_at, thread_id FROM dragging_issues WHERE issue_id = ?",
                (actionable_id,)
            ).fetchone()

        if not act_row:
            raise HTTPException(status_code=404, detail="Actionable item not found.")

        act_dict = dict(act_row)
        thread_id = act_dict.get("thread_id")
        thread_dict = None

        if thread_id:
            t_row = cursor.execute("SELECT * FROM threads WHERE thread_id = ?", (thread_id,)).fetchone()
            if t_row:
                thread_dict = dict(t_row)

        if not thread_dict and act_dict.get("title"):
            clean_title = act_dict["title"].replace("'", "").replace('"', "")
            terms = [t for t in clean_title.split() if len(t) > 3][:3]
            if terms:
                like_term = "%" + "%".join(terms) + "%"
                t_row = cursor.execute("SELECT * FROM threads WHERE subject LIKE ? OR raw_text LIKE ? LIMIT 1", (like_term, like_term)).fetchone()
                if t_row:
                    thread_dict = dict(t_row)

        if not thread_dict:
            t_row = cursor.execute("SELECT * FROM threads ORDER BY rowid DESC LIMIT 1").fetchone()
            if t_row:
                thread_dict = dict(t_row)

    # Parse raw_text into structured chat messages
    messages = []
    if thread_dict and thread_dict.get("raw_text"):
        raw_text = thread_dict["raw_text"]
        pattern = re.compile(r"^\[(.*?)\]\s*([^:]+):\s*(.*)$")
        
        for line in raw_text.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            match = pattern.match(line_str)
            if match:
                ts, sender, text = match.groups()
                messages.append({
                    "timestamp": ts.strip(),
                    "sender": sender.strip(),
                    "text": text.strip()
                })
            else:
                if messages:
                    messages[-1]["text"] += "\n" + line_str
                else:
                    messages.append({
                        "timestamp": thread_dict.get("first_message_at") or "",
                        "sender": thread_dict.get("participants", "Participant").split(",")[0].strip(),
                        "text": line_str
                    })

    # Fallback if no structured messages extracted
    if not messages and thread_dict and thread_dict.get("raw_text"):
        messages.append({
            "timestamp": thread_dict.get("first_message_at") or act_dict.get("created_at") or "",
            "sender": (thread_dict.get("participants") or "Thread Participant").split(",")[0].strip(),
            "text": thread_dict["raw_text"]
        })

    return {
        "success": True,
        "actionable": act_dict,
        "thread": thread_dict,
        "messages": messages
    }
