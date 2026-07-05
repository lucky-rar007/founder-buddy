"""
Microsoft Graph authentication client.

Handles OAuth2 Client Credentials flow for
obtaining Microsoft Graph access tokens.
"""

from __future__ import annotations

from datetime import datetime, timedelta, UTC
from typing import Any

import requests

from ..config.settings import settings


class AuthenticationError(Exception):
    """Raised when Microsoft Graph authentication fails."""


class GraphAuthenticator:
    """
    Handles Microsoft Graph authentication
    with in-memory token caching.
    """

    TOKEN_URL_TEMPLATE = (
        "https://login.microsoftonline.com/"
        "{tenant_id}/oauth2/v2.0/token"
    )

    def __init__(self) -> None:
        self.token_url = self.TOKEN_URL_TEMPLATE.format(
            tenant_id=settings.azure_tenant_id
        )

        self._access_token: str | None = None
        self._expires_at: datetime | None = None

    def get_access_token(self) -> str:
        """
        Return a valid access token.

        Uses cached token when possible.
        """

        if self._is_token_valid():
            return self._access_token  # type: ignore

        self._refresh_token()

        return self._access_token  # type: ignore

    def _is_token_valid(self) -> bool:
        """
        Check whether cached token exists
        and has not expired.
        """

        if self._access_token is None:
            return False

        if self._expires_at is None:
            return False

        return datetime.now(UTC) < self._expires_at

    def _refresh_token(self) -> None:
        """
        Request a new token from Microsoft.
        """

        payload = {
            "client_id": settings.azure_client_id,
            "client_secret": settings.azure_client_secret,
            "scope": settings.graph_scope,
            "grant_type": "client_credentials",
        }

        try:
            response = requests.post(
                self.token_url,
                data=payload,
                timeout=30,
            )

            response.raise_for_status()

        except requests.RequestException as exc:
            raise AuthenticationError(
                f"Failed to obtain access token: {exc}"
            ) from exc

        data: dict[str, Any] = response.json()

        access_token = data.get("access_token")

        if not access_token:
            raise AuthenticationError(
                "Access token missing from response."
            )

        expires_in = int(
            data.get("expires_in", 3600)
        )

        self._access_token = access_token

        self._expires_at = (
            datetime.now(UTC)
            + timedelta(seconds=expires_in - 60)
        )

authenticator = GraphAuthenticator()