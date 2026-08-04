"""
Ingestion API Routes.

Handles range configuration, fetching teams and channels, retrieving sync progress,
and orchestrating the live sync via WebSockets.
"""

from __future__ import annotations

import logging
import asyncio
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from shared.database import get_db, get_config, set_config
from ingestion.graph_client import graph_client
from ingestion.engine import IngestionEngine

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────
# REQUEST MODELS
# ─────────────────────────────────────────────────────────────────────

from typing import List, Optional, Literal

class ExcludedChannelModel(BaseModel):
    team_id: str
    team_name: Optional[str] = "Unknown Team"
    channel_id: str
    channel_name: Optional[str] = "Unknown Channel"


class ConfigureIngestionRequest(BaseModel):
    date_range: Literal["6_months", "12_months", "5_years", "10_years", "start"]
    outlook_user_id: Optional[str] = "me"
    excluded_channels: List[ExcludedChannelModel]


# ─────────────────────────────────────────────────────────────────────
# API ENDPOINTS
# ─────────────────────────────────────────────────────────────────────

@router.get("/users")
async def get_org_users():
    """
    Fetch organization users from Microsoft Graph API for Outlook mail selection auto-suggest.
    """
    try:
        raw_users = graph_client.get_users()
        users = []
        for u in raw_users:
            display_name = u.get("displayName", "Unknown User")
            user_mail = u.get("mail") or u.get("userPrincipalName") or ""
            user_id = u.get("id") or user_mail
            if user_mail or display_name:
                users.append({
                    "id": user_id,
                    "name": display_name,
                    "mail": user_mail,
                    "userPrincipalName": u.get("userPrincipalName", "")
                })

        return {"success": True, "users": users}
    except Exception as e:
        logging.warning(f"[API] Failed to fetch Graph API users: {e}")
        # Return fallback default "me" option + friendly error
        return {
            "success": True,
            "users": [
                {"id": "me", "name": "Current User (Me)", "mail": "me@organization.com"}
            ],
            "error": str(e)
        }


@router.get("/teams")
async def get_teams_and_channels():
    """
    Fetch all available teams and channels from Microsoft Graph API
    so the user can select exclusions.
    """
    try:
        teams_data = graph_client.get_teams()
        tree = []

        for team in teams_data:
            t_id = team["id"]
            t_name = team.get("displayName", "Unknown Team")
            
            try:
                channels_data = graph_client.get_channels(t_id)
                channels = []
                for ch in channels_data:
                    channels.append({
                        "id": ch["id"],
                        "name": ch.get("displayName", "Unknown Channel")
                    })
                tree.append({
                    "id": t_id,
                    "name": t_name,
                    "channels": channels
                })
            except Exception as ce:
                logging.warning(f"[API] Failed to fetch channels for team {t_name} ({t_id}): {ce}")
                tree.append({
                    "id": t_id,
                    "name": t_name,
                    "channels": [],
                    "error": str(ce)
                })

        return {"success": True, "teams": tree}

    except Exception as e:
        logging.error(f"[API] Failed to fetch teams: {e}")
        warning_msg = (
            "Azure Permission Missing (HTTP 403): Grant 'Group.Read.All' or 'Team.ReadBasic.All' permission in Azure AD "
            "(portal.azure.com → App registrations → API permissions → Grant admin consent)."
            if ("403" in str(e) or "Forbidden" in str(e))
            else f"Could not retrieve Teams and Channels: {str(e)}"
        )
        return {
            "success": True,
            "teams": [],
            "warning": warning_msg
        }


@router.post("/configure")
async def configure_ingestion(req: ConfigureIngestionRequest):
    """
    Save date range and channel exclusions to DB.
    """
    try:
        set_config("ingestion_date_range", req.date_range)
        set_config("outlook_user_id", req.outlook_user_id or "me")

        # Overwrite exclusions
        with get_db() as conn:
            conn.execute("DELETE FROM excluded_channels")
            for ch in req.excluded_channels:
                conn.execute(
                    """INSERT INTO excluded_channels
                       (team_id, team_name, channel_id, channel_name)
                       VALUES (?, ?, ?, ?)""",
                    (ch.team_id, ch.team_name, ch.channel_id, ch.channel_name)
                )

        logging.info("[API] Saved ingestion configuration.")
        return {"success": True, "message": "Ingestion configuration saved."}

    except Exception as e:
        logging.error(f"[API] Configuration failure: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to save configuration: {str(e)}"
        )


@router.get("/status")
async def get_ingestion_status():
    """
    Retrieve current sync status, progress metrics, and initial sync completion status.
    """
    try:
        engine = IngestionEngine()
        
        # Check if database has any logs (i.e. if setup was run)
        with get_db() as conn:
            log_count = conn.execute("SELECT COUNT(*) FROM ingestion_log").fetchone()[0]

        has_started = log_count > 0
        stats = engine.get_sync_stats() if has_started else None
        completed = get_config("initial_sync_completed") is not None

        return {
            "success": True,
            "has_started": has_started,
            "completed": completed,
            "date_range": get_config("ingestion_date_range"),
            "outlook_user_id": get_config("outlook_user_id"),
            "completed_at": get_config("initial_sync_completed"),
            "stats": stats
        }
    except Exception as e:
        logging.error(f"[API] Failed to get sync status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reset")
async def reset_ingestion():
    """
    Reset ingestion log to allow a clean full sync re-run.
    """
    try:
        with get_db() as conn:
            conn.execute("DELETE FROM ingestion_log")
            conn.execute("DELETE FROM excluded_channels")
        set_config("initial_sync_completed", "", encrypt=False)
        set_config("ingestion_date_range", "", encrypt=False)
        # Delete completed setting
        from shared.database import delete_config
        delete_config("initial_sync_completed")
        delete_config("ingestion_date_range")

        logging.info("[API] Ingestion state reset.")
        return {"success": True, "message": "Sync log cleared."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────
# LIVE PROGRESS WEBSOCKET
# ─────────────────────────────────────────────────────────────────────

@router.websocket("/progress")
async def websocket_progress(websocket: WebSocket):
    """
    WebSocket endpoint for triggering the initial sync and streaming
    real-time progress back to the loading screen.
    """
    await websocket.accept()
    logging.info("[WebSocket] Client connected for ingestion progress.")

    active_engine: Optional[IngestionEngine] = None

    async def send_ws_message(msg: dict):
        try:
            from starlette.websockets import WebSocketState
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json(msg)
        except Exception:
            pass

    try:
        # 1. Instantiate the dynamic sync engine with our websocket callback
        active_engine = IngestionEngine(ws_callback=send_ws_message)

        # 2. Trigger the sync run in the background (using standard asyncio/concurrency)
        sync_task = asyncio.create_task(active_engine.run_sync())

        # 3. Keep the websocket channel alive, listening for incoming messages (e.g. cancellation)
        while not sync_task.done():
            try:
                # Wait for potential messages from the client (e.g. cancel commands)
                # Using short timeout to allow looping and checking task completion
                data = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                if data == "cancel" and active_engine:
                    logging.info("[WebSocket] Cancel requested by client.")
                    active_engine.cancel()
            except asyncio.TimeoutError:
                # Normal path: loop continues and checks if sync_task completed
                pass

        # Ensure task exceptions are surfaced
        await sync_task

    except WebSocketDisconnect:
        logging.info("[WebSocket] Client disconnected. Cancelling active sync task...")
        if active_engine:
            active_engine.cancel()
    except Exception as e:
        logging.error(f"[WebSocket] Error in progress task: {e}")
        await send_ws_message({"type": "error", "message": str(e)})
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
        logging.info("[WebSocket] Progress connection closed.")
