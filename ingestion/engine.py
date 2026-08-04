"""
Day-by-Day Ingestion Engine.

Orchestrates day-by-day ingestion of Teams and Outlook messages,
maintains sync state in SQLite, and communicates progress via WebSockets.
"""

from __future__ import annotations

import os
import json
import logging
import asyncio
from datetime import datetime, timedelta, date
from pathlib import Path

import requests

from shared.database import get_db, get_config, set_config
from shared.settings import settings
from ingestion.auth import authenticator

logger = logging.getLogger(__name__)

_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent

# ─────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────

def sanitize_filename(name: str) -> str:
    import re
    return re.sub(r'[\\/*?:"<>| ]', "_", name)


def calculate_cutoff_date(range_option: str) -> date:
    """Calculate the cutoff start date based on user selection."""
    today = datetime.now().date()
    if range_option == "6_months":
        return today - timedelta(days=6 * 30)
    elif range_option == "12_months":
        return today - timedelta(days=12 * 30)
    elif range_option == "5_years":
        return today - timedelta(days=5 * 365)
    elif range_option == "10_years":
        return today - timedelta(days=10 * 365)
    elif range_option == "start":
        # Default to 15 years ago
        return today - timedelta(days=15 * 365)
    else:
        # Default fallback: 6 months
        return today - timedelta(days=6 * 30)


# ─────────────────────────────────────────────────────────────────────
# BATCHING & RETRY CLIENT
# ─────────────────────────────────────────────────────────────────────

class DynamicIngestionClient:
    """Graph API client wrapper that supports page yielding and batching replies."""

    def __init__(self):
        self.base_url = settings.graph_api_base_url

    def _get_headers(self) -> dict[str, str]:
        token = authenticator.get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    def _make_request(self, method: str, url: str, json_body: dict | None = None, max_retries: int = 3) -> requests.Response:
        headers = self._get_headers()
        for attempt in range(max_retries + 1):
            try:
                response = requests.request(method, url, headers=headers, json=json_body, timeout=30)
                if response.status_code == 401:
                    if attempt < max_retries:
                        logger.warning("[Ingestion Client] 401 Unauthorized - refreshing token")
                        authenticator.refresh_token()
                        headers = self._get_headers()
                        continue
                elif response.status_code == 400:
                    err_msg = ""
                    try:
                        err_msg = response.json().get("error", {}).get("message", "")
                    except Exception:
                        pass
                    logger.warning(f"[Ingestion Client] HTTP 400 Bad Request on {url}: {err_msg or response.text[:200]}")
                    response.raise_for_status()
                response.raise_for_status()
                return response
            except requests.exceptions.HTTPError as http_err:
                # Do not retry non-transient 4xx client errors (400, 403, 404)
                if response is not None and response.status_code in (400, 403, 404):
                    raise http_err
                if attempt < max_retries:
                    import time
                    time.sleep(2)
                    continue
                raise http_err
            except Exception as e:
                if attempt < max_retries:
                    import time
                    time.sleep(2)
                    continue
                raise e
        raise Exception("Graph API request failed after retries")

    async def get_pages(self, url: str, params: dict | None = None):
        """Yield pages of results from an OData nextLink endpoint asynchronously."""
        current_url = url
        if params:
            from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse
            url_parts = list(urlparse(current_url))
            query = dict(parse_qsl(url_parts[4]))
            query.update(params)
            url_parts[4] = urlencode(query, safe="$,:")
            current_url = urlunparse(url_parts)

        while current_url:
            data = None
            for page_retry in range(1, 4):
                try:
                    response = await asyncio.to_thread(self._make_request, "GET", current_url)
                    data = response.json()
                    break
                except Exception as exc:
                    logger.warning(f"[Ingestion Engine] Pagination request failed (Attempt {page_retry}/3): {exc}")
                    if page_retry < 3:
                        await asyncio.sleep(2 * page_retry)
            if not data:
                break
            yield data.get("value", [])
            current_url = data.get("@odata.nextLink")

    async def get_replies_batch(self, team_id: str, channel_id: str, message_ids: list[str]) -> dict[str, list[dict]]:
        """Retrieve replies for message IDs using JSON Batching (max 20 requests per batch) asynchronously."""
        if not message_ids:
            return {}

        batch_url = f"{self.base_url}/$batch"
        all_replies = {}

        # Partition into chunks of 20
        chunks = [message_ids[i:i + 20] for i in range(0, len(message_ids), 20)]

        from urllib.parse import quote
        for chunk in chunks:
            requests_payload = []
            for msg_id in chunk:
                requests_payload.append({
                    "id": msg_id,
                    "method": "GET",
                    "url": f"/teams/{quote(team_id, safe='')}/channels/{quote(channel_id, safe='')}/messages/{quote(msg_id, safe='')}/replies"
                })

            try:
                response = await asyncio.to_thread(self._make_request, "POST", batch_url, {"requests": requests_payload})
                data = response.json()
                for resp in data.get("responses", []):
                    req_id = resp.get("id")
                    status = resp.get("status", 200)
                    if status == 200:
                        replies = resp.get("body", {}).get("value", [])
                        filtered = []
                        for r in replies:
                            if r.get("messageType") == "systemEventMessage":
                                continue
                            filtered.append(r)
                        all_replies[req_id] = filtered
                    else:
                        all_replies[req_id] = []
            except Exception as e:
                logger.error(f"[Ingestion Client] Batch request failed: {e}")
                for msg_id in chunk:
                    all_replies[msg_id] = []

        return all_replies


# ─────────────────────────────────────────────────────────────────────
# INGESTION ENGINE
# ─────────────────────────────────────────────────────────────────────

class IngestionEngine:
    """Manages the full sync and day-by-day ingestion."""

    def __init__(self, ws_callback=None):
        self.client = DynamicIngestionClient()
        self.ws_callback = ws_callback  # Async callback function: ws_callback(dict)
        self.is_cancelled = False

    async def _send_progress(self, type_: str, payload: dict):
        if self.ws_callback:
            try:
                await self.ws_callback({"type": type_, **payload})
            except Exception as e:
                logger.error(f"[Ingestion Engine] Failed to send WS progress: {e}")

    def cancel(self):
        self.is_cancelled = True

    def get_excluded_channels(self) -> set[str]:
        """Fetch set of excluded channel_ids from DB."""
        with get_db() as conn:
            rows = conn.execute("SELECT channel_id FROM excluded_channels").fetchall()
        return {r["channel_id"] for r in rows}

    def prepare_ingestion_log(self, start_date: date, sources: list[dict]):
        """
        Initialize pending rows in ingestion_log for all sources and days.
        Respects per-source creation date (e.g. channel creation date) if newer than user start_date.
        Avoids duplicates using INSERT OR IGNORE.
        """
        today = datetime.now().date()

        with get_db() as conn:
            for src in sources:
                # Per-source effective start date
                source_start = start_date
                created_str = src.get("created_at", "")
                if created_str:
                    try:
                        c_date = datetime.fromisoformat(created_str[:10]).date()
                        if c_date > source_start:
                            source_start = c_date
                    except ValueError:
                        pass

                curr = source_start
                while curr <= today:
                    d_str = curr.strftime("%Y-%m-%d")
                    conn.execute(
                        """INSERT OR IGNORE INTO ingestion_log
                           (source, source_entity, target_date, status)
                           VALUES (?, ?, ?, 'pending')""",
                        (src["source"], src["entity_id"], d_str)
                    )
                    curr += timedelta(days=1)

    def get_sync_stats(self) -> dict:
        """Calculate completed vs total pending sync days and total ingested messages count."""
        with get_db() as conn:
            row = conn.execute(
                """SELECT
                     COUNT(*) as total,
                     SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                     SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                     SUM(COALESCE(messages_count, 0)) as total_messages
                   FROM ingestion_log"""
            ).fetchone()
        
        total = row["total"] or 0
        completed = row["completed"] or 0
        failed = row["failed"] or 0
        total_messages = row["total_messages"] or 0
        pending = max(0, total - completed - failed)

        return {
            "total_days": total,
            "completed_days": completed,
            "failed_days": failed,
            "pending_days": pending,
            "total_messages": total_messages,
            "percent": round((completed / total * 100) if total > 0 else 100, 1)
        }

    async def run_sync(self):
        """Run the initial dynamic sync process."""
        self.is_cancelled = False

        # 1. Fetch range configuration
        range_option = get_config("ingestion_date_range") or "6_months"
        cutoff_date = calculate_cutoff_date(range_option)
        cutoff_datetime = datetime.combine(cutoff_date, datetime.min.time())

        # 2. Get active sources (Teams + Outlook)
        sources = []

        # Find Teams / Channels not excluded
        excluded_ids = self.get_excluded_channels()
        try:
            # Let's import graph_client dynamically to use existing endpoints
            from ingestion.graph_client import graph_client
            teams = graph_client.get_teams()
            for t in teams:
                t_id = t["id"]
                t_name = t.get("displayName", "Unknown Team")
                channels = graph_client.get_channels(t_id)
                for ch in channels:
                    ch_id = ch["id"]
                    ch_name = ch.get("displayName", "Unknown Channel")
                    if ch_id not in excluded_ids:
                        sources.append({
                            "source": "teams",
                            "entity_id": f"{t_id}:{ch_id}",
                            "display_name": f"{t_name} > {ch_name}",
                            "team_id": t_id,
                            "channel_id": ch_id,
                            "team_name": t_name,
                            "channel_name": ch_name,
                            "created_at": ch.get("createdDateTime", "")
                        })
        except Exception as e:
            logger.error(f"[Ingestion Engine] Failed to fetch Teams/Channels for setup: {e}")
            await self._send_progress("error", {"message": f"Graph API error: {e}"})
            return

        # Outlook source (User selected or 'me')
        user_email = get_config("outlook_user_id") or "me"
        sources.append({
            "source": "outlook",
            "entity_id": user_email,
            "display_name": f"Outlook Inbox ({user_email})",
            "user_id": user_email
        })

        # 3. Initialize ingestion log
        self.prepare_ingestion_log(cutoff_date, sources)

        # 4. Notify setup complete
        stats = self.get_sync_stats()
        await self._send_progress("sync_start", stats)

        # 5. Ingest each source paginating backwards
        for src in sources:
            if self.is_cancelled:
                break

            await self._send_progress("source_start", {"source_name": src["display_name"]})

            if src["source"] == "teams":
                await self.ingest_teams_source(src, cutoff_datetime)
            else:
                await self.ingest_outlook_source(src, cutoff_date)

        # 6. Mark onboarding completed / initial sync finished & run dashboard analysis pipeline
        if not self.is_cancelled:
            set_config("initial_sync_completed", datetime.now().isoformat())
            try:
                from dashboard.pipeline import run_full_pipeline
                from shared.settings import settings
                logger.info("[Ingestion Engine] Ingestion complete. Auto-running dashboard analysis pipeline...")

                loop = asyncio.get_running_loop()
                def sync_pipe_callback(event_type, data):
                    try:
                        asyncio.run_coroutine_threadsafe(
                            self._send_progress(event_type, data),
                            loop
                        )
                    except Exception:
                        pass

                await self._send_progress("pipeline_start", {"message": "Building threads and running AI event extraction..."})
                await asyncio.to_thread(
                    run_full_pipeline,
                    api_key=settings.gemini_api_key,
                    run_type="initial_sync",
                    progress_callback=sync_pipe_callback
                )
                logger.info("[Ingestion Engine] Dashboard analysis pipeline completed successfully.")
            except Exception as pe:
                logger.error(f"[Ingestion Engine] Auto-pipeline error: {pe}")

            await self._send_progress("sync_complete", self.get_sync_stats())

    # ─── Teams Ingestion Flow ──────────────────────────────────

    async def ingest_teams_source(self, src: dict, cutoff_dt: datetime):
        team_id = src["team_id"]
        channel_id = src["channel_id"]
        entity_id = src["entity_id"]
        clean_team = sanitize_filename(src["team_name"])
        clean_channel = sanitize_filename(src["channel_name"])

        # Bounding cutoff date by channel creation date
        created_str = src.get("created_at", "")
        if created_str:
            try:
                ch_created_dt = datetime.fromisoformat(created_str[:19])
                if ch_created_dt > cutoff_dt:
                    cutoff_dt = ch_created_dt
            except ValueError:
                pass

        pointer_date = datetime.now().date()
        today_str = pointer_date.strftime("%Y-%m-%d")

        # Mark source run starting in DB log
        with get_db() as conn:
            conn.execute(
                "UPDATE ingestion_log SET status = 'in_progress', started_at = ? WHERE source = 'teams' AND source_entity = ? AND status = 'pending'",
                (datetime.now().isoformat(), entity_id)
            )

        from urllib.parse import quote
        messages_url = f"{self.client.base_url}/teams/{quote(team_id, safe='')}/channels/{quote(channel_id, safe='')}/messages"
        params = {"$top": 50}

        grouped_messages: dict[str, list[dict]] = {}

        try:
            async for page in self.client.get_pages(messages_url, params=params):
                if self.is_cancelled:
                    break

                if not page:
                    break

                root_message_ids = []
                valid_root_messages = []

                # Filter and identify cutoff
                reached_cutoff = False
                for msg in page:
                    if msg.get("messageType") == "systemEventMessage":
                        continue

                    # Check date
                    created_str = msg.get("createdDateTime", "")
                    if created_str:
                        try:
                            msg_dt = datetime.fromisoformat(created_str[:19])
                            if msg_dt < cutoff_dt:
                                reached_cutoff = True
                                break
                        except ValueError:
                            pass

                    root_message_ids.append(msg["id"])
                    valid_root_messages.append(msg)

                # Fetch replies for valid messages
                replies_map = await self.client.get_replies_batch(team_id, channel_id, root_message_ids)

                # Attach replies and group by date
                for msg in valid_root_messages:
                    msg_id = msg["id"]
                    msg["replies"] = replies_map.get(msg_id, [])

                    created_str = msg.get("createdDateTime", "")
                    if created_str:
                        date_str = created_str[:10]
                        if date_str not in grouped_messages:
                            grouped_messages[date_str] = []
                        grouped_messages[date_str].append(msg)

                if reached_cutoff:
                    break

                # Save completed days as we move backward
                # Find the oldest date in the current page
                if valid_root_messages:
                    oldest_created = valid_root_messages[-1].get("createdDateTime", "")
                    if oldest_created:
                        oldest_date_str = oldest_created[:10]
                        try:
                            oldest_date = datetime.strptime(oldest_date_str, "%Y-%m-%d").date()
                            # We can safely save and complete days from pointer_date down to oldest_date
                            while pointer_date >= oldest_date:
                                p_str = pointer_date.strftime("%Y-%m-%d")
                                day_msgs = grouped_messages.pop(p_str, [])
                                self.save_day_teams_messages(day_msgs, p_str, clean_team, clean_channel)
                                total_teams_count = sum(1 + len(m.get("replies", [])) for m in day_msgs)
                                self.mark_day_completed("teams", entity_id, p_str, total_teams_count)
                                pointer_date -= timedelta(days=1)
                        except ValueError:
                            pass

                if reached_cutoff:
                    break

                # Yield to FastAPI async loop
                await asyncio.sleep(0.01)

            # Save any remaining grouped messages and mark all remaining days in range completed
            for d_str, msgs in list(grouped_messages.items()):
                self.save_day_teams_messages(msgs, d_str, clean_team, clean_channel)
                total_teams_count = sum(1 + len(m.get("replies", [])) for m in msgs)
                self.mark_day_completed("teams", entity_id, d_str, total_teams_count)

            # Mark all pending remaining days in the sync range as completed (empty days)
            with get_db() as conn:
                conn.execute(
                    """UPDATE ingestion_log
                       SET status = 'completed', completed_at = ?, messages_count = 0
                       WHERE source = 'teams' AND source_entity = ? AND status IN ('pending', 'in_progress')""",
                    (datetime.now().isoformat(), entity_id)
                )

            # Send progress
            await self._send_progress("progress_update", self.get_sync_stats())

        except Exception as e:
            logger.error(f"[Ingestion Engine] Teams ingestion error: {e}")
            # Mark active/pending runs as failed
            with get_db() as conn:
                conn.execute(
                    """UPDATE ingestion_log
                       SET status = 'failed', error_message = ?, completed_at = ?
                       WHERE source = 'teams' AND source_entity = ? AND status IN ('pending', 'in_progress')""",
                    (str(e), datetime.now().isoformat(), entity_id)
                )
            await self._send_progress("progress_update", self.get_sync_stats())

    def save_day_teams_messages(self, messages: list[dict], date_str: str, clean_team: str, clean_channel: str):
        if not messages:
            return

        base_dir = _WORKSPACE_ROOT / "data" / "raw_teams_messages" / date_str
        base_dir.mkdir(parents=True, exist_ok=True)
        file_path = base_dir / f"{date_str}.{clean_team}.{clean_channel}.json"

        # Dedup-merge existing file
        if file_path.exists():
            try:
                existing = json.loads(file_path.read_text(encoding="utf-8"))
                if isinstance(existing, list):
                    seen = {m["id"] for m in messages if "id" in m}
                    for item in existing:
                        if item.get("id") not in seen:
                            messages.append(item)
            except Exception as e:
                logger.warning(f"Error merging Teams messages: {e}")

        file_path.write_text(json.dumps(messages, indent=2, ensure_ascii=False), encoding="utf-8")

    # ─── Outlook Ingestion Flow ────────────────────────────────

    async def ingest_outlook_source(self, src: dict, cutoff_date: date):
        user_id = src["user_id"]
        entity_id = src["entity_id"]
        
        if user_id == "me":
            try:
                from ingestion.graph_client import graph_client
                users = graph_client.get_users()
                if users:
                    user_id = users[0].get("userPrincipalName") or users[0]["id"]
                    logger.info(f"[Ingestion Engine] Bypassing 'me' in app-only mode. Resolved to user: {user_id}")
            except Exception as e:
                logger.error(f"[Ingestion Engine] Failed to lookup users for 'me' fallback: {e}")

        clean_user = sanitize_filename(user_id)
        pointer_date = datetime.now().date()

        # Mark source run starting in DB log
        with get_db() as conn:
            conn.execute(
                "UPDATE ingestion_log SET status = 'in_progress', started_at = ? WHERE source = 'outlook' AND source_entity = ? AND status = 'pending'",
                (datetime.now().isoformat(), entity_id)
            )

        inbox_url = f"{self.client.base_url}/users/{user_id}/mailFolders/inbox/messages"

        # Apply orderby desc
        params = {
            "$top": 50,
            "$select": "id,subject,body,from,toRecipients,ccRecipients,conversationId,receivedDateTime,importance",
            "$orderby": "receivedDateTime desc"
        }

        # Filter emails since cutoff
        formatted_cutoff = cutoff_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        params["$filter"] = f"receivedDateTime ge {formatted_cutoff}"

        grouped_messages: dict[str, list[dict]] = {}

        try:
            async for page in self.client.get_pages(inbox_url, params=params):
                if self.is_cancelled:
                    break

                if not page:
                    break

                for email in page:
                    received_str = email.get("receivedDateTime", "")
                    if received_str:
                        date_str = received_str[:10]
                        if date_str not in grouped_messages:
                            grouped_messages[date_str] = []
                        grouped_messages[date_str].append(email)

                # Save completed days as we move backward
                if page:
                    oldest_received = page[-1].get("receivedDateTime", "")
                    if oldest_received:
                        oldest_date_str = oldest_received[:10]
                        try:
                            oldest_date = datetime.strptime(oldest_date_str, "%Y-%m-%d").date()
                            while pointer_date >= oldest_date:
                                p_str = pointer_date.strftime("%Y-%m-%d")
                                day_msgs = grouped_messages.pop(p_str, [])
                                self.save_day_outlook_messages(day_msgs, p_str, clean_user)
                                self.mark_day_completed("outlook", entity_id, p_str, len(day_msgs))
                                pointer_date -= timedelta(days=1)
                        except ValueError:
                            pass

                # Yield to FastAPI async loop
                await asyncio.sleep(0.01)

            # Save remaining emails
            for d_str, msgs in list(grouped_messages.items()):
                self.save_day_outlook_messages(msgs, d_str, clean_user)
                self.mark_day_completed("outlook", entity_id, d_str, len(msgs))

            # Mark all pending remaining days in the sync range as completed (empty days)
            with get_db() as conn:
                conn.execute(
                    """UPDATE ingestion_log
                       SET status = 'completed', completed_at = ?, messages_count = 0
                       WHERE source = 'outlook' AND source_entity = ? AND status IN ('pending', 'in_progress')""",
                    (datetime.now().isoformat(), entity_id)
                )

            # Send progress
            await self._send_progress("progress_update", self.get_sync_stats())

        except Exception as e:
            logger.error(f"[Ingestion Engine] Outlook ingestion error: {e}")
            with get_db() as conn:
                conn.execute(
                    """UPDATE ingestion_log
                       SET status = 'failed', error_message = ?, completed_at = ?
                       WHERE source = 'outlook' AND source_entity = ? AND status IN ('pending', 'in_progress')""",
                    (str(e), datetime.now().isoformat(), entity_id)
                )
            await self._send_progress("progress_update", self.get_sync_stats())

    def save_day_outlook_messages(self, messages: list[dict], date_str: str, clean_user: str):
        if not messages:
            return

        base_dir = _WORKSPACE_ROOT / "data" / "raw_outlook_messages" / date_str
        base_dir.mkdir(parents=True, exist_ok=True)
        file_path = base_dir / f"{date_str}.{clean_user}.outlook.json"

        # Dedup-merge existing file
        if file_path.exists():
            try:
                existing = json.loads(file_path.read_text(encoding="utf-8"))
                if isinstance(existing, list):
                    seen = {m["id"] for m in messages if "id" in m}
                    for item in existing:
                        if item.get("id") not in seen:
                            messages.append(item)
            except Exception as e:
                logger.warning(f"Error merging Outlook messages: {e}")

        file_path.write_text(json.dumps(messages, indent=2, ensure_ascii=False), encoding="utf-8")

    # ─── DB Completion helpers ─────────────────────────────────

    def mark_day_completed(self, source: str, entity_id: str, date_str: str, count: int):
        with get_db() as conn:
            conn.execute(
                """UPDATE ingestion_log
                   SET status = 'completed', completed_at = ?, messages_count = ?
                   WHERE source = ? AND source_entity = ? AND target_date = ?""",
                (datetime.now().isoformat(), count, source, entity_id, date_str)
            )
        # Safely fire progress update — only if an event loop is running
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._send_progress("progress_update", self.get_sync_stats()))
        except RuntimeError:
            pass  # No event loop available (CLI mode or sync caller)
