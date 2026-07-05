from __future__ import annotations

from typing import Any
from urllib.parse import urlencode
import time
import logging

import requests

from .auth import authenticator
from ..config.settings import settings


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
            query_string = urlencode(params)
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
        data = self.get("/users")
        return data.get("value", [])

    def get_teams(self) -> list[dict[str, Any]]:
        endpoint = (
            "/groups"
            "?$filter=resourceProvisioningOptions/Any"
            "(x:x eq 'Team')"
        )

        data = self.get(endpoint)
        return data.get("value", [])

    def get_channels(self, team_id: str) -> list[dict[str, Any]]:
        data = self.get(f"/teams/{team_id}/channels")
        return data.get("value", [])

    def get_messages(self, team_id: str, channel_id: str) -> list[dict[str, Any]]:
        data = self.get(
            f"/teams/{team_id}/channels/{channel_id}/messages"
        )
        return data.get("value", [])

    def get_replies(
        self,
        team_id: str,
        channel_id: str,
        message_id: str,
    ) -> list[dict[str, Any]]:
        data = self.get(
            f"/teams/{team_id}/channels/"
            f"{channel_id}/messages/"
            f"{message_id}/replies"
        )
        return data.get("value", [])


graph_client = GraphClient()