"""
Thread Builder Orchestrator.

Processes raw day-by-day JSON messages from Teams and Outlook,
compiles them into structured conversation threads, and persists them to SQLite.
"""

from __future__ import annotations

import json
import hashlib
import logging
from pathlib import Path
from datetime import datetime

from shared.database import get_db
from threads.parsers import (
    clean_message_body,
    extract_participants_from_teams,
    extract_participants_from_outlook,
    strip_html_tags,
    has_only_attachment_content
)

from typing import Any

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent


class ThreadBuilder:
    """
    Transforms raw JSON files into structured, normalized database Thread objects.
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or (_WORKSPACE_ROOT / "data")

    # ─── Teams Threads Compiler ────────────────────────────────
    
    def build_teams_threads_for_date(self, date_str: str) -> list[dict[str, Any]]:
        """
        Build thread objects from raw Teams JSON logs for a specific day.
        """
        teams_dir = self.data_dir / "raw_teams_messages" / date_str
        if not teams_dir.exists():
            return []

        threads = []

        for json_file in teams_dir.glob("*.json"):
            try:
                messages = json.loads(json_file.read_text(encoding="utf-8"))
                if not isinstance(messages, list):
                    continue

                # Extract Team/Channel from name: YYYY-MM-DD.TeamName.ChannelName.json
                parts = json_file.stem.split(".")
                team_name = parts[1].replace("_", " ") if len(parts) > 1 else "Unknown"
                channel_name = parts[2].replace("_", " ") if len(parts) > 2 else "Unknown"

                for msg in messages:
                    if msg.get("messageType") == "systemEventMessage":
                        continue

                    from_info = msg.get("from") or {}
                    user_obj = from_info.get("user") or from_info.get("application") or from_info.get("device") or {}
                    first_sender = user_obj.get("displayName") or "Team Member"

                    msg_attachments = msg.get("attachments") or []

                    # Skip messages whose body is purely an attachment with no text
                    if has_only_attachment_content(msg.get("body", {}), msg_attachments):
                        continue

                    first_msg_text = clean_message_body(msg.get("body", {}), msg_attachments)

                    # Skip if actual message content is empty after cleaning
                    if not first_msg_text.strip():
                        continue

                    first_ts = msg.get("createdDateTime", "")[:19]

                    thread_lines = [f"[{first_ts}] {first_sender}: {first_msg_text}"]

                    replies = msg.get("replies", [])
                    for reply in replies:
                        if reply.get("messageType") == "systemEventMessage":
                            continue
                        r_from = reply.get("from") or {}
                        r_user = r_from.get("user") or r_from.get("application") or {}
                        r_sender = r_user.get("displayName") or "Team Member"
                        r_attachments = reply.get("attachments") or []
                        r_text = clean_message_body(reply.get("body", {}), r_attachments)
                        # Skip reply if it's empty after cleaning (attachment-only reply)
                        if not r_text.strip():
                            continue
                        r_ts = reply.get("createdDateTime", "")[:19]
                        thread_lines.append(f"[{r_ts}] {r_sender}: {r_text}")

                    raw_text = "\n".join(thread_lines)
                    # Guard: skip thread if the combined content has no real substance
                    if len(raw_text.strip()) < 20:
                        continue

                    # Subject line: prioritize subject field or truncate first message
                    subject = msg.get("subject", "") or ""
                    if not subject:
                        subject = first_msg_text[:80] + ("..." if len(first_msg_text) > 80 else "")
                    if not subject.strip():
                        subject = "No Subject"

                    # Collect participants
                    participants = extract_participants_from_teams(msg)

                    # Deterministic thread_id
                    source_id = msg.get("id", "")
                    thread_id = f"th_{hashlib.md5(source_id.encode()).hexdigest()[:12]}"

                    last_ts = replies[-1].get("createdDateTime", "")[:19] if replies else first_ts

                    # Pre-calculate token estimate (1 token ≈ 4 chars, conservative)
                    estimated_tokens = len(raw_text) // 4

                    threads.append({
                        "thread_id": thread_id,
                        "source": "teams",
                        "source_id": source_id,
                        "subject": subject,
                        "participants": ", ".join(sorted(participants)),
                        "message_count": 1 + len(replies),
                        "first_message_at": first_ts,
                        "last_message_at": last_ts,
                        "raw_text": raw_text,
                        "estimated_tokens": estimated_tokens,
                        "team_name": team_name,
                        "channel_name": channel_name,
                        "thread_date": date_str,
                        "metadata_json": json.dumps({
                            "reply_count": len(replies),
                            "importance": msg.get("importance", "normal")
                        })
                    })
            except Exception as e:
                logging.error(f"[ThreadBuilder] Error building Teams threads from {json_file}: {e}")

        return threads

    # ─── Outlook Threads Compiler ──────────────────────────────
    
    def build_outlook_threads_for_date(self, date_str: str) -> list[dict[str, Any]]:
        """
        Build thread objects from raw Outlook JSON logs for a specific day.
        Groups emails by conversationId.
        """
        outlook_dir = self.data_dir / "raw_outlook_messages" / date_str
        if not outlook_dir.exists():
            return []

        conversations = {}

        for json_file in outlook_dir.glob("*.json"):
            try:
                emails = json.loads(json_file.read_text(encoding="utf-8"))
                if not isinstance(emails, list):
                    continue

                for email in emails:
                    conv_id = email.get("conversationId") or email.get("id")
                    if not conv_id:
                        continue
                    if conv_id not in conversations:
                        conversations[conv_id] = []
                    conversations[conv_id].append(email)
            except Exception as e:
                logging.error(f"[ThreadBuilder] Error parsing Outlook file {json_file}: {e}")

        threads = []

        for conv_id, emails in conversations.items():
            try:
                # Sort chronologically
                emails.sort(key=lambda e: e.get("receivedDateTime", ""))

                thread_lines = []
                participants = set()

                for email in emails:
                    sender = email.get("from", {}).get("emailAddress", {}).get("name", "Unknown")
                    parts = extract_participants_from_outlook(email)
                    participants.update(parts)

                    # Outlook emails: pass no attachments list (body text is always plain/html)
                    body_text = clean_message_body(email.get("body", {}))
                    ts = email.get("receivedDateTime", "")[:19]
                    # Only append if there's actual text content
                    if body_text.strip():
                        thread_lines.append(f"[{ts}] {sender}: {body_text}")

                raw_text = "\n".join(thread_lines)
                if len(raw_text.strip()) < 20:
                    continue

                subject = emails[0].get("subject", "No Subject")
                first_ts = emails[0].get("receivedDateTime", "")[:19]
                last_ts = emails[-1].get("receivedDateTime", "")[:19]

                thread_id = f"th_{hashlib.md5(conv_id.encode()).hexdigest()[:12]}"

                # Pre-calculate token estimate (1 token ≈ 4 chars, conservative)
                estimated_tokens = len(raw_text) // 4

                threads.append({
                    "thread_id": thread_id,
                    "source": "outlook",
                    "source_id": conv_id,
                    "subject": subject,
                    "participants": ", ".join(sorted(participants)),
                    "message_count": len(emails),
                    "first_message_at": first_ts,
                    "last_message_at": last_ts,
                    "raw_text": raw_text,
                    "estimated_tokens": estimated_tokens,
                    "team_name": "",
                    "channel_name": "",
                    "thread_date": date_str,
                    "metadata_json": json.dumps({
                        "has_attachments": any(email.get("hasAttachments", False) for email in emails),
                        "importance": emails[0].get("importance", "normal")
                    })
                })
            except Exception as e:
                logging.error(f"[ThreadBuilder] Failed to compile Outlook conversation {conv_id}: {e}")

        return threads

    # ─── Orchestrator / SQLite Inserter ─────────────────────────
    
    def save_threads_to_db(self, threads: list[dict[str, Any]]) -> int:
        """Write compiled thread records to SQLite threads table."""
        if not threads:
            return 0

        inserted = 0
        from dashboard.db import add_audit_log
        with get_db() as conn:
            for t in threads:
                conn.execute(
                    """INSERT OR REPLACE INTO threads
                       (thread_id, source, source_id, subject, participants, message_count,
                        first_message_at, last_message_at, raw_text, estimated_tokens,
                        team_name, channel_name, thread_date, metadata_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        t["thread_id"], t["source"], t["source_id"], t["subject"],
                        t["participants"], t["message_count"], t["first_message_at"],
                        t["last_message_at"], t["raw_text"], t.get("estimated_tokens", 0),
                        t["team_name"], t["channel_name"], t["thread_date"], t["metadata_json"]
                    )
                )
                inserted += 1

                # Audit Logbook Entry
                add_audit_log(
                    log_date=t.get("thread_date", datetime.now().strftime("%Y-%m-%d")),
                    stage="thread_building",
                    event_type="THREAD_CREATED",
                    entity_id=t["thread_id"],
                    details={
                        "source": t["source"],
                        "subject": t["subject"],
                        "participants": t["participants"],
                        "message_count": t["message_count"],
                        "estimated_tokens": t.get("estimated_tokens", 0)
                    }
                )

        return inserted

    def build_pending_threads(self) -> int:
        """
        Scans raw Teams and Outlook message directories and builds threads for all
        folders that exist in data/.
        """
        teams_base = self.data_dir / "raw_teams_messages"
        outlook_base = self.data_dir / "raw_outlook_messages"

        # Find all dates across both folders
        all_dates = set()
        if teams_base.exists():
            all_dates.update(d.name for d in teams_base.iterdir() if d.is_dir())
        if outlook_base.exists():
            all_dates.update(d.name for d in outlook_base.iterdir() if d.is_dir())

        total_inserted = 0

        for d_str in sorted(all_dates):
            logging.info(f"[ThreadBuilder] Processing date: {d_str}")
            teams_threads = self.build_teams_threads_for_date(d_str)
            outlook_threads = self.build_outlook_threads_for_date(d_str)
            
            all_threads = teams_threads + outlook_threads
            inserted = self.save_threads_to_db(all_threads)
            total_inserted += inserted
            
            if inserted > 0:
                logging.info(f"[ThreadBuilder] Saved {inserted} threads for date {d_str}")

        return total_inserted
