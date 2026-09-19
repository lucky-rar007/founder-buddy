from __future__ import annotations

from typing import Any
from urllib.parse import urlencode
import random
import time
import logging

import requests

from ingestion.auth import authenticator
from shared.settings import settings


class GraphAPIError(Exception):
    """Raised when a Microsoft Graph API request fails."""


class GraphClient:
    """
    Client for interacting with Microsoft Graph.
    """

    def __init__(self) -> None:
        self.authenticator = authenticator

    def _get_headers(self) -> dict[str, str]:
        """
        Build authenticated request headers.
        """
        token = self.authenticator.get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute GET request against Microsoft Graph API.
        Handles OData pagination automatically.

        Args:
            endpoint: API path (e.g. "/me/messages")
            params: Optional query parameters

        Returns:
            Aggregated response data with all pages concatenated in "value" list
        """
        base_url = "https://graph.microsoft.com/v1.0"
        url = f"{base_url}{endpoint}"

        if params:
            url = f"{url}?{urlencode(params)}"

        all_values: list[Any] = []

        try:
            while url:
                response = self._make_request_with_retry(url)
                data = response.json()

                if isinstance(data, dict) and "value" in data:
                    all_values.extend(data["value"])

                url = data.get("@odata.nextLink")

        except requests.RequestException as exc:
            raise GraphAPIError(
                f"Graph API request failed: {exc}"
            ) from exc

        return {"value": all_values}

    def _make_request_with_retry(
        self,
        url: str,
        max_retries: int = 4,
    ) -> requests.Response:
        """
        Execute GET request with retry logic for 401 (auth), 429 (rate limit),
        and 5xx server errors with exponential backoff and jitter.

        Args:
            url: Full request URL
            max_retries: Number of retries for auth/rate limit/server errors

        Returns:
            Response object

        Raises:
            requests.RequestException: If request fails after retries
        """
        last_exception: Exception | None = None

        for attempt in range(max_retries + 1):
            # Timeout escalation: 30s -> 45s -> 60s -> 75s -> 90s
            timeout = 30 + (attempt * 15)

            try:
                response = requests.get(
                    url,
                    headers=self._get_headers(),
                    timeout=timeout,
                )
            except (requests.Timeout, requests.ConnectionError) as net_err:
                last_exception = net_err
                if attempt < max_retries:
                    backoff = min(2 ** (attempt + 1) + random.uniform(0.5, 2.0), 60.0)
                    logging.warning(
                        f"[GraphClient] Network error ({net_err.__class__.__name__}) on attempt {attempt + 1}/{max_retries + 1}. "
                        f"Retrying in {backoff:.1f}s with timeout={timeout + 15}s..."
                    )
                    time.sleep(backoff)
                    continue
                else:
                    raise

            # Handle 401 Unauthorized - refresh token and retry
            if response.status_code == 401:
                if attempt < max_retries:
                    logging.warning("[GraphClient] Received 401 - refreshing token and retrying...")
                    self.authenticator.refresh_token()
                    continue
                else:
                    response.raise_for_status()

            # Handle 429 Rate Limited - read Retry-After and backoff with jitter
            if response.status_code == 429:
                if attempt < max_retries:
                    retry_header = response.headers.get("Retry-After")
                    try:
                        retry_after = float(retry_header) if retry_header else 2.0 ** (attempt + 1)
                    except (ValueError, TypeError):
                        retry_after = 2.0 ** (attempt + 1)
                    # Add jitter
                    sleep_time = min(retry_after + random.uniform(0.2, 1.5), 60.0)
                    logging.warning(
                        f"[GraphClient] Rate limited (429) - waiting {sleep_time:.1f}s before retry (attempt {attempt + 1}/{max_retries + 1})"
                    )
                    time.sleep(sleep_time)
                    continue
                else:
                    response.raise_for_status()

            # Handle 5xx Server Errors (500, 502, 503, 504) with exponential backoff & jitter
            if 500 <= response.status_code < 600:
                if attempt < max_retries:
                    backoff = min(2 ** (attempt + 1) + random.uniform(0.2, 1.5), 60.0)
                    logging.warning(
                        f"[GraphClient] Server error ({response.status_code}) on attempt {attempt + 1}/{max_retries + 1}. "
                        f"Backing off {backoff:.1f}s..."
                    )
                    time.sleep(backoff)
                    continue
                else:
                    response.raise_for_status()

            # Success or client error (4xx other than 401/429)
            response.raise_for_status()
            return response

        if last_exception:
            raise last_exception
        return response

    def get_users(self) -> list[dict[str, Any]]:
        """
        Retrieves organization users for Outlook mail account selection.
        """
        try:
            data = self.get("/users?$select=id,displayName,mail,userPrincipalName")
            if data and "value" in data and len(data["value"]) > 0:
                return data["value"]
        except Exception as e:
            logging.warning(f"[GraphClient] Select users query failed ({e}). Trying base /users...")

        try:
            data = self.get("/users")
            return data.get("value", [])
        except Exception as e:
            logging.error(f"[GraphClient] Failed to fetch /users: {e}")
            return []

    def get_teams(self) -> list[dict[str, Any]]:
        """
        Retrieves all Microsoft Teams in the directory.
        Tries filtered /groups first, then falls back to /groups with client-side filter.
        Handles HTTP 403 Forbidden gracefully if Group.Read.All permission is missing.
        """
        # Attempt 1: Filtered OData query
        try:
            endpoint = "/groups?$filter=resourceProvisioningOptions/Any(x:x eq 'Team')"
            data = self.get(endpoint)
            if data and "value" in data:
                return data["value"]
        except Exception as e:
            logging.warning(f"[GraphClient] Filtered teams query failed ({e}). Trying fallback query...")

        # Attempt 2: Select query with client-side filter
        try:
            endpoint = "/groups?$select=id,displayName,resourceProvisioningOptions"
            data = self.get(endpoint)
            if data and "value" in data:
                teams = []
                for g in data["value"]:
                    opts = g.get("resourceProvisioningOptions") or []
                    if "Team" in opts:
                        teams.append(g)
                if teams:
                    return teams
                return data["value"]
        except Exception as e:
            logging.warning(f"[GraphClient] Select groups query failed ({e}). Trying base /groups...")

        # Attempt 3: Base /groups query
        try:
            data = self.get("/groups")
            return data.get("value", [])
        except Exception as e:
            logging.error(f"[GraphClient] All teams/groups queries failed: {e}")
            if "403" in str(e) or "Forbidden" in str(e):
                logging.warning("[GraphClient] 403 Forbidden on /groups. Ensure 'Group.Read.All' or 'Team.ReadBasic.All' permission is granted in Azure AD.")
                return []
            raise

    def get_channels(self, team_id: str) -> list[dict[str, Any]]:
        from urllib.parse import quote
        data = self.get(f"/teams/{quote(team_id, safe='')}/channels")
        return data.get("value", [])

    def get_messages(self, team_id: str, channel_id: str) -> list[dict[str, Any]]:
        from urllib.parse import quote
        data = self.get(
            f"/teams/{quote(team_id, safe='')}/channels/{quote(channel_id, safe='')}/messages"
        )
        return data.get("value", [])

    def get_replies(
        self,
        team_id: str,
        channel_id: str,
        message_id: str,
    ) -> list[dict[str, Any]]:
        from urllib.parse import quote
        data = self.get(
            f"/teams/{quote(team_id, safe='')}/channels/"
            f"{quote(channel_id, safe='')}/messages/"
            f"{quote(message_id, safe='')}/replies"
        )
        return data.get("value", [])


graph_client = GraphClient()
