"""
Application configuration management.

Loads environment variables from .env,
validates required settings, and exposes
a singleton settings object for the application.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


class ConfigurationError(Exception):
    """Raised when required configuration is missing."""


@dataclass(frozen=True)
class Settings:
    """
    Application settings loaded from environment variables.
    """

    # Microsoft Graph Authentication
    azure_tenant_id: str
    azure_client_id: str
    azure_client_secret: str

    # Microsoft Graph Configuration
    graph_api_base_url: str
    graph_scope: str

    # Application Configuration
    data_dir: str
    log_level: str

    @classmethod
    def load(cls) -> "Settings":
        """
        Load and validate configuration from environment variables.

        Returns:
            Settings: Validated application settings.

        Raises:
            ConfigurationError: If required environment variables are missing.
        """

        required_variables = {
            "AZURE_TENANT_ID": os.getenv("AZURE_TENANT_ID"),
            "AZURE_CLIENT_ID": os.getenv("AZURE_CLIENT_ID"),
            "AZURE_CLIENT_SECRET": os.getenv("AZURE_CLIENT_SECRET"),
        }

        missing_variables = [
            key
            for key, value in required_variables.items()
            if not value
        ]

        if missing_variables:
            raise ConfigurationError(
                "Missing required environment variables: "
                + ", ".join(missing_variables)
            )

        return cls(
            azure_tenant_id=required_variables["AZURE_TENANT_ID"],
            azure_client_id=required_variables["AZURE_CLIENT_ID"],
            azure_client_secret=required_variables["AZURE_CLIENT_SECRET"],
            graph_api_base_url=os.getenv(
                "GRAPH_API_BASE_URL",
                "https://graph.microsoft.com/v1.0",
            ),
            graph_scope=os.getenv(
                "GRAPH_SCOPE",
                "https://graph.microsoft.com/.default",
            ),
            data_dir=os.getenv(
                "DATA_DIR",
                "data",
            ),
            log_level=os.getenv(
                "LOG_LEVEL",
                "INFO",
            ),
        )


settings = Settings.load()