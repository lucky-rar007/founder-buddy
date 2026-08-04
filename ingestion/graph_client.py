from __future__ import annotations

from typing import Any
from urllib.parse import urlencode
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

        access_token = self.authenticator.get_access_token()

        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    def get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute GET request with pagination support and retry logic.

        Args:
            endpoint: API endpoint (e.g., "/users", "/me/mailFolders/inbox/messages")
            params: Query parameters dict (e.g., {"$top": 50, "$select": "id,name"})

        Returns:
            Response dict with paginated results in "value" key
        """
        url = f"{settings.graph_api_base_url}{endpoint}"

        if params:
            query_string = urlencode(params, safe="$,:")
            url = f"{url}?{query_string}"

        all_values = []

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
        max_retries: int = 2,
    ) -> requests.Response:
        """
        Execute GET request with retry logic for 401 (auth) and 429 (rate limit).

        Args:
            url: Full request URL
            max_retries: Number of retries for auth/rate limit errors

        Returns:
            Response object

        Raises:
            requests.RequestException: If request fails after retries
        """
        for attempt in range(max_retries + 1):
            response = requests.get(
                url,
                headers=self._get_headers(),
                timeout=30,
            )

            # Handle 401 Unauthorized - refresh token and retry
            if response.status_code == 401:
                if attempt < max_retries:
                    logging.warning("Received 401 - refreshing token and retrying")
                    self.authenticator.refresh_token()
                    continue
                else:
                    response.raise_for_status()

            # Handle 429 Rate Limited - read Retry-After and backoff
            if response.status_code == 429:
                if attempt < max_retries:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    logging.warning(
                        f"Rate limited (429) - waiting {retry_after}s before retry"
                    )
                    time.sleep(retry_after)
                    continue
                else:
                    response.raise_for_status()

            # Success or non-retryable error
            response.raise_for_status()
            return response

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
