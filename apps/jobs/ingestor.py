import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
import json
import logging
import time
import requests
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ─────────────────────────────────────────────────────────────────────
# PATH RESOLUTION & ENV LOADING
# ─────────────────────────────────────────────────────────────────────

# Load environment from the workspace root's .env file
workspace_root = Path(__file__).resolve().parents[2]
dotenv_path = workspace_root / ".env"
if dotenv_path.exists():
    load_dotenv(dotenv_path=dotenv_path)
else:
    logging.warning(f"Could not find .env file at {dotenv_path}")

# Add workspace root to sys.path so we can import packages
if str(workspace_root) not in sys.path:
    sys.path.append(str(workspace_root))

try:
    from packages.shared.graph_core.config.settings import settings
    from packages.shared.graph_core.clients.auth import authenticator
    from packages.shared.graph_core.utils.selector_cli import SelectorCLI
    from packages.shared.graph_core.clients.graph_client import graph_client
except ImportError as e:
    logging.error("Failed to import modules from local packages.shared.graph_core. "
                  "Verify local files exist and dependencies are installed.")
    raise e

# ─────────────────────────────────────────────────────────────────────
# CUSTOM ROBUST GRAPH CLIENT WITH BATCHING
# ─────────────────────────────────────────────────────────────────────

class IngestionGraphClient:
    """
    Enhanced Graph client that implements JSON batching and robust date filtering.
    """

    def __init__(self):
        self.base_url = settings.graph_api_base_url
        self.auth = authenticator

    def _get_headers(self) -> dict[str, str]:
        token = self.auth.get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    def get_with_pagination(self, url: str, params: dict | None = None, cutoff_date: datetime | None = None, date_field: str = "createdDateTime") -> list[dict]:
        """
        Retrieves paginated resources. If cutoff_date is specified and the item's date_field
        is older than the cutoff_date, it stops fetching further pages.
        """
        headers = self._get_headers()
        all_items = []
        current_url = url
        
        if params:
            from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse
            # Combine params with current url
            url_parts = list(urlparse(current_url))
            query = dict(parse_qsl(url_parts[4]))
            query.update(params)
            url_parts[4] = urlencode(query)
            current_url = urlunparse(url_parts)

        while current_url:
            logging.info(f"Fetching page: {current_url}")
            try:
                response = self._make_request_with_retry("GET", current_url, headers=headers)
                data = response.json()
            except Exception as exc:
                logging.error(f"Graph API request failed on {current_url}: {exc}")
                break

            items = data.get("value", [])
            page_filtered_items = []
            stop_pagination = False

            for item in items:
                # System message filtering for Teams (keeps only user messages)
                if "messageType" in item:
                    if item.get("messageType") == "systemEventMessage":
                        continue
                    from_info = item.get("from")
                    if not from_info or not from_info.get("user"):
                        continue

                # Check date cutoff
                if cutoff_date and date_field in item:
                    item_date_str = item[date_field]
                    if item_date_str:
                        # Extract first 19 chars (YYYY-MM-DDTHH:MM:SS)
                        try:
                            item_date = datetime.fromisoformat(item_date_str[:19])
                            if item_date < cutoff_date:
                                # Since API returns in descending order, we can stop pagination here
                                stop_pagination = True
                                break
                        except ValueError:
                            pass

                page_filtered_items.append(item)

            all_items.extend(page_filtered_items)
            
            if stop_pagination:
                logging.info("Reached date cutoff limit. Stopping page fetch.")
                break

            current_url = data.get("@odata.nextLink")

        return all_items

    def _make_request_with_retry(self, method: str, url: str, headers: dict, json_body: dict | None = None, max_retries: int = 3) -> requests.Response:
        for attempt in range(max_retries + 1):
            try:
                response = requests.request(method, url, headers=headers, json=json_body, timeout=30)
                
                if response.status_code == 401:
                    if attempt < max_retries:
                        logging.warning("Received 401 - refreshing token and retrying")
                        self.auth.refresh_token()
                        headers["Authorization"] = f"Bearer {self.auth.get_access_token()}"
                        continue
                    else:
                        response.raise_for_status()

                if response.status_code == 429:
                    if attempt < max_retries:
                        retry_after = int(response.headers.get("Retry-After", 5))
                        logging.warning(f"Rate limited (429) - waiting {retry_after}s before retry")
                        time.sleep(retry_after)
                        continue
                    else:
                        response.raise_for_status()

                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                if attempt < max_retries:
                    logging.warning(f"Network error: {exc}. Retrying in 5s...")
                    time.sleep(5)
                else:
                    raise exc
        return response

    def get_replies_batch(self, team_id: str, channel_id: str, message_ids: list[str]) -> dict[str, list[dict]]:
        """
        Retrieves replies for multiple message IDs using Microsoft Graph JSON Batching.
        Groups requests into batches of 20 to avoid rate limits.
        """
        headers = self._get_headers()
        batch_url = f"{self.base_url}/$batch"
        all_replies = {}

        # Partition message IDs into chunks of 20
        chunks = [message_ids[i:i + 20] for i in range(0, len(message_ids), 20)]

        for chunk_index, chunk in enumerate(chunks):
            logging.info(f"Executing batch query {chunk_index + 1}/{len(chunks)} for {len(chunk)} message replies...")
            
            # Construct batch request payload
            requests_payload = []
            for idx, msg_id in enumerate(chunk):
                requests_payload.append({
                    "id": msg_id,
                    "method": "GET",
                    "url": f"/teams/{team_id}/channels/{channel_id}/messages/{msg_id}/replies"
                })

            try:
                response = self._make_request_with_retry("POST", batch_url, headers=headers, json_body={"requests": requests_payload})
                data = response.json()
                
                for resp in data.get("responses", []):
                    req_id = resp.get("id")
                    status = resp.get("status", 200)
                    if status == 200:
                        replies = resp.get("body", {}).get("value", [])
                        # Filter system messages in replies (keeps only user replies)
                        filtered_replies = []
                        for r in replies:
                            if "messageType" in r:
                                if r.get("messageType") == "systemEventMessage":
                                    continue
                                from_info = r.get("from")
                                if not from_info or not from_info.get("user"):
                                    continue
                            filtered_replies.append(r)
                        all_replies[req_id] = filtered_replies
                    else:
                        logging.warning(f"Failed to fetch replies for message {req_id} inside batch (Status {status}): {resp.get('body')}")
                        all_replies[req_id] = []
            except Exception as e:
                logging.error(f"Batch request failed: {e}")
                # Fallback to empty lists for this chunk
                for msg_id in chunk:
                    all_replies[msg_id] = []

        return all_replies


# ─────────────────────────────────────────────────────────────────────
# DATA INGESTION OPERATIONS
# ─────────────────────────────────────────────────────────────────────

def ingest_teams(team_id: str, channel_id: str, cutoff_date: datetime | None = None):
    client = IngestionGraphClient()

    if team_id.lower() == "all":
        try:
            teams = graph_client.get_teams()
            team_ids = [t["id"] for t in teams if "id" in t]
            team_names = {t["id"]: t.get("displayName", t["id"]) for t in teams if "id" in t}
        except Exception as e:
            logging.error(f"Failed to fetch teams: {e}")
            return
    else:
        team_ids = [team_id]
        team_names = {team_id: "Selected Team"}

    if not team_ids:
        logging.info("No teams found to ingest.")
        return

    for t_id in team_ids:
        t_name = team_names.get(t_id, t_id)
        logging.info(f"Ingesting for Team: {t_name} ({t_id})")
        
        if channel_id.lower() == "all":
            try:
                channels = graph_client.get_channels(t_id)
                channel_ids = [ch["id"] for ch in channels if "id" in ch]
                channel_names = {ch["id"]: ch.get("displayName", ch["id"]) for ch in channels if "id" in ch}
            except Exception as e:
                logging.error(f"Failed to fetch channels for team {t_name} ({t_id}): {e}")
                continue
        else:
            channel_ids = [channel_id]
            channel_names = {channel_id: "selected channel"}

        if not channel_ids:
            logging.info(f"No channels found to ingest for team {t_name} ({t_id}).")
            continue

        for ch_id in channel_ids:
            ch_name = channel_names.get(ch_id, ch_id)
            logging.info(f"Starting Teams ingestion. Team: {t_name} ({t_id}), Channel: {ch_name} ({ch_id}), Cutoff: {cutoff_date}")

            # Fetch root messages (applying client-side cutoff page-breaker)
            messages_url = f"{client.base_url}/teams/{t_id}/channels/{ch_id}/messages"
            try:
                root_messages = client.get_with_pagination(
                    url=messages_url,
                    params={"$top": 50},
                    cutoff_date=cutoff_date,
                    date_field="createdDateTime"
                )
            except Exception as e:
                logging.error(f"Failed to fetch messages for channel {ch_name} ({ch_id}) in team {t_name}: {e}")
                continue

            if not root_messages:
                logging.info(f"No new Teams messages found since the cutoff date in channel {ch_name} ({ch_id}) under team {t_name}.")
                continue

            # Fetch replies in batch for all root messages that are not system messages
            message_ids = [m["id"] for m in root_messages if "id" in m]
            logging.info(f"Found {len(root_messages)} messages in channel {ch_name}. Fetching replies in batch...")
            
            try:
                replies_map = client.get_replies_batch(t_id, ch_id, message_ids)
            except Exception as e:
                logging.error(f"Failed to fetch replies for channel {ch_name} ({ch_id}) in team {t_name}: {e}")
                replies_map = {}

            # Attach replies to root messages
            for msg in root_messages:
                msg_id = msg.get("id")
                msg["replies"] = replies_map.get(msg_id, [])

            # Group messages by date and save them
            save_teams_messages(root_messages, team_name=t_name, channel_name=ch_name)


def ingest_outlook(user_id: str, cutoff_date: datetime | None = None):
    client = IngestionGraphClient()
    logging.info(f"Starting Outlook ingestion. User: {user_id}, Cutoff: {cutoff_date}")

    # Prepare request params with server-side date filter if cutoff exists
    params = {
        "$top": 50,
        "$select": "id,subject,body,from,toRecipients,ccRecipients,conversationId,receivedDateTime,importance",
        "$orderby": "receivedDateTime desc"
    }

    if cutoff_date:
        # Format date as: YYYY-MM-DDTHH:MM:SSZ
        formatted_cutoff = cutoff_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        params["$filter"] = f"receivedDateTime ge {formatted_cutoff}"

    inbox_url = f"{client.base_url}/users/{user_id}/mailFolders/inbox/messages"
    if user_id == "me":
        inbox_url = f"{client.base_url}/me/mailFolders/inbox/messages"

    emails = client.get_with_pagination(
        url=inbox_url,
        params=params,
        cutoff_date=cutoff_date,
        date_field="receivedDateTime"
    )

    if not emails:
        logging.info("No new Outlook messages found since the cutoff date.")
        return

    # Group and save
    save_outlook_messages(emails, user_id)


# ─────────────────────────────────────────────────────────────────────
# FILE WRITING UTILITIES (WITH DEDUPLICATION MERGING)
# ─────────────────────────────────────────────────────────────────────

def save_teams_messages(messages: list[dict], team_name: str, channel_name: str):
    import re
    def sanitize(name: str) -> str:
        return re.sub(r'[\\/*?:"<>| ]', "_", name)

    clean_team = sanitize(team_name)
    clean_channel = sanitize(channel_name)

    grouped = {}
    for msg in messages:
        dt_str = msg.get("createdDateTime")
        if not dt_str:
            continue
        date_key = dt_str[:10]  # 'YYYY-MM-DD'
        if date_key not in grouped:
            grouped[date_key] = []
        grouped[date_key].append(msg)
        
    base_dir = Path(__file__).resolve().parents[2] / "packages" / "raw_data" / "raw teams messges"
    
    for date_key, msgs in grouped.items():
        # Create output directory for the specific date
        output_dir = base_dir / date_key
        output_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = output_dir / f"{date_key}.{clean_team}.{clean_channel}.json"
        
        # Merge if file exists
        if file_path.exists():
            try:
                existing = json.loads(file_path.read_text(encoding="utf-8"))
                if isinstance(existing, list):
                    seen_ids = {m.get("id") for m in msgs if m.get("id")}
                    for item in existing:
                        if item.get("id") not in seen_ids:
                            msgs.append(item)
            except Exception as e:
                logging.warning(f"Error reading existing file {file_path}: {e}")

        file_path.write_text(json.dumps(msgs, indent=2, ensure_ascii=False), encoding="utf-8")
        logging.info(f"Saved {len(msgs)} Teams messages to {file_path}")


def save_outlook_messages(messages: list[dict], user_id: str):
    import re
    def sanitize(name: str) -> str:
        return re.sub(r'[\\/*?:"<>| ]', "_", name)

    clean_user = sanitize(user_id)

    grouped = {}
    for msg in messages:
        dt_str = msg.get("receivedDateTime")
        if not dt_str:
            continue
        date_key = dt_str[:10]  # 'YYYY-MM-DD'
        if date_key not in grouped:
            grouped[date_key] = []
        grouped[date_key].append(msg)
        
    base_dir = Path(__file__).resolve().parents[2] / "packages" / "raw_data" / "raw outlook messages"
    
    for date_key, msgs in grouped.items():
        # Create output directory for the specific date
        output_dir = base_dir / date_key
        output_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = output_dir / f"{date_key}.{clean_user}.outlook.json"
        
        # Merge if file exists
        if file_path.exists():
            try:
                existing = json.loads(file_path.read_text(encoding="utf-8"))
                if isinstance(existing, list):
                    seen_ids = {m.get("id") for m in msgs if m.get("id")}
                    for item in existing:
                        if item.get("id") not in seen_ids:
                            msgs.append(item)
            except Exception as e:
                logging.warning(f"Error reading existing file {file_path}: {e}")

        file_path.write_text(json.dumps(msgs, indent=2, ensure_ascii=False), encoding="utf-8")
        logging.info(f"Saved {len(msgs)} Outlook emails to {file_path}")


# ─────────────────────────────────────────────────────────────────────
# RUN IMPLEMENTATION FLOWS
# ─────────────────────────────────────────────────────────────────────

def run_manual():
    logging.info("=== MANUAL INGESTION RUN ===")
    
    print("\nSelect Source:")
    print("  [0] Teams")
    print("  [1] Outlook")
    
    source_choice = input("Enter choice (0 or 1): ").strip()
    while source_choice not in ("0", "1"):
        source_choice = input("Invalid — enter 0 or 1: ").strip()

    # Get Cutoff Date Option
    print("\nSelect Date Cutoff Option:")
    print("  [0] Ingest all messages")
    print("  [1] Custom date cutoff (YYYY-MM-DD)")
    cutoff_choice = input("Enter choice (0 or 1): ").strip()
    while cutoff_choice not in ("0", "1"):
        cutoff_choice = input("Invalid — enter 0 or 1: ").strip()

    cutoff_date = None
    if cutoff_choice == "1":
        while True:
            date_input = input("Enter cutoff date (YYYY-MM-DD): ").strip()
            try:
                cutoff_date = datetime.strptime(date_input, "%Y-%m-%d")
                break
            except ValueError:
                print("Invalid date format. Use YYYY-MM-DD.")

    selector = SelectorCLI()
    if source_choice == "0":
        team_id = selector.select_team()
        if team_id == "all":
            channel_id = "all"
        else:
            channel_id = selector.select_channel(team_id)
        ingest_teams(team_id, channel_id, cutoff_date)
    else:
        user_id, _ = selector.select_user()
        ingest_outlook(user_id, cutoff_date)

    logging.info("Manual ingestion completed successfully.")


def configure_schedule():
    logging.info("=== CONFIGURE SCHEDULER ===")
    selector = SelectorCLI()
    
    print("\nConfigure Teams source for scheduling:")
    team_id = selector.select_team()
    if team_id == "all":
        channel_id = "all"
    else:
        channel_id = selector.select_channel(team_id)

    print("\nConfigure Outlook user for scheduling:")
    user_id, _ = selector.select_user()

    config_data = {
        "teams": {
            "team_id": team_id,
            "channel_id": channel_id
        },
        "outlook": {
            "user_id": user_id
        }
    }

    config_dir = Path("config")
    config_dir.mkdir(exist_ok=True)
    config_file = config_dir / "scheduler_config.json"
    config_file.write_text(json.dumps(config_data, indent=2), encoding="utf-8")
    
    logging.info(f"Scheduler configuration saved to {config_file}")
    return config_data


def run_scheduler_daemon():
    logging.info("=== STARTING SCHEDULER DAEMON ===")
    config_file = Path("config/scheduler_config.json")
    
    if not config_file.exists():
        logging.info("No scheduler configuration found. Starting interactive configuration...")
        config_data = configure_schedule()
    else:
        config_data = json.loads(config_file.read_text(encoding="utf-8"))

    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    
    scheduler = BlockingScheduler(timezone="Asia/Kolkata")
    
    def scheduled_job():
        logging.info("Executing scheduled ingestion...")
        # Daily at 6 AM IST means we fetch messages since yesterday at 00:00:00
        yesterday_midnight = datetime.now() - timedelta(days=1)
        yesterday_midnight = yesterday_midnight.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # 1. Ingest Teams
        try:
            teams_conf = config_data.get("teams", {})
            if teams_conf.get("team_id") and teams_conf.get("channel_id"):
                ingest_teams(teams_conf["team_id"], teams_conf["channel_id"], yesterday_midnight)
        except Exception as e:
            logging.error(f"Scheduled Teams Ingestion failed: {e}")

        # 2. Ingest Outlook
        try:
            outlook_conf = config_data.get("outlook", {})
            if outlook_conf.get("user_id"):
                ingest_outlook(outlook_conf["user_id"], yesterday_midnight)
        except Exception as e:
            logging.error(f"Scheduled Outlook Ingestion failed: {e}")

        logging.info("Scheduled ingestion task completed.")

    # Schedule run daily at 6:00 AM IST
    scheduler.add_job(
        func=scheduled_job,
        trigger=CronTrigger(hour=6, minute=0, timezone="Asia/Kolkata"),
        id="daily_ingestion_6am",
        name="Daily Ingestion at 6:00 AM IST",
        replace_existing=True
    )
    
    logging.info("Scheduler configured: daily at 06:00 AM Asia/Kolkata")
    logging.info("Press Ctrl+C to exit.")
    
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logging.info("Scheduler daemon stopped.")


# ─────────────────────────────────────────────────────────────────────
# CLI ENTRYPOINT
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Founder Buddy Ingestor Client CLI")
    parser.add_argument("mode", choices=["manual", "schedule", "configure-schedule"], help="Running mode")
    
    args = parser.parse_args()
    
    try:
        if args.mode == "manual":
            run_manual()
        elif args.mode == "configure-schedule":
            configure_schedule()
        elif args.mode == "schedule":
            run_scheduler_daemon()
    except KeyboardInterrupt:
        print("\nExiting application gracefully...")
        sys.exit(0)
