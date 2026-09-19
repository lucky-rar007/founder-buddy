"""
Application configuration management.

Loads settings from SQLite database config with Fernet encryption.
Automatically migrates legacy .env credentials into SQLite app_config
and deletes the .env file on startup to enforce secure persistent storage.
"""

from __future__ import annotations

import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
_DOTENV_PATH = _WORKSPACE_ROOT / ".env"


def migrate_and_remove_env() -> None:
    """
    Migrates any existing .env credential key-value pairs into the encrypted SQLite database
    and safely deletes the .env file.
    """
    if not _DOTENV_PATH.exists():
        return

    logger.info("[Settings Migration] Legacy .env file detected. Migrating credentials to encrypted SQLite storage...")

    try:
        from dotenv import dotenv_values
        from shared.database import set_config

        env_dict = dotenv_values(_DOTENV_PATH)

        # Migrate Azure credentials
        tenant_id = env_dict.get("AZURE_TENANT_ID", "").strip()
        client_id = env_dict.get("AZURE_CLIENT_ID", "").strip()
        client_secret = env_dict.get("AZURE_CLIENT_SECRET", "").strip()

        if tenant_id:
            set_config("azure_tenant_id", tenant_id)
        if client_id:
            set_config("azure_client_id", client_id)
        if client_secret:
            set_config("azure_client_secret", client_secret, encrypt=True)

        # Migrate Graph API defaults
        base_url = env_dict.get("GRAPH_API_BASE_URL", "https://graph.microsoft.com/v1.0").strip()
        scope = env_dict.get("GRAPH_SCOPE", "https://graph.microsoft.com/.default").strip()
        set_config("graph_api_base_url", base_url)
        set_config("graph_scope", scope)

        # Migrate Gemini credentials
        gemini_key = env_dict.get("GEMINI_API_KEY", "").strip()
        gemini_model = env_dict.get("GEMINI_MODEL_NAME", "gemini-3.5-flash-lite").strip()

        if gemini_key:
            set_config("gemini_api_key", gemini_key, encrypt=True)
        set_config("gemini_model_name", gemini_model)

        # Mark onboarding completed if credentials exist
        if tenant_id and client_id and client_secret and gemini_key:
            from shared.database import is_onboarded
            if not is_onboarded():
                from datetime import datetime
                set_config("onboarding_completed", datetime.now().isoformat())

        # Delete the .env file
        try:
            os.remove(_DOTENV_PATH)
            logger.info("[Settings Migration] Legacy .env file successfully migrated and deleted.")
        except Exception as de:
            logger.warning(f"[Settings Migration Warning] Could not remove .env file: {de}")

    except Exception as e:
        logger.error(f"[Settings Migration Error] Failed to migrate .env credentials: {e}")


class Settings:
    """
    Application settings dynamically loaded from SQLite database config
    with zero dependence on .env files.
    """

    def _get_setting(self, key: str, env_fallback: str | None = None, default: str = "") -> str:
        """Generic helper to fetch a config key with environment variable and default fallback."""
        try:
            from shared.database import get_config
            val = get_config(key)
            if val is not None and val != "":
                return val
        except Exception:
            pass
        if env_fallback:
            env_val = os.getenv(env_fallback)
            if env_val:
                return env_val
        return default

    @property
    def azure_tenant_id(self) -> str:
        return self._get_setting("azure_tenant_id", "AZURE_TENANT_ID", "")

    @property
    def azure_client_id(self) -> str:
        return self._get_setting("azure_client_id", "AZURE_CLIENT_ID", "")

    @property
    def azure_client_secret(self) -> str:
        return self._get_setting("azure_client_secret", "AZURE_CLIENT_SECRET", "")

    @property
    def graph_api_base_url(self) -> str:
        return self._get_setting("graph_api_base_url", "GRAPH_API_BASE_URL", "https://graph.microsoft.com/v1.0")

    @property
    def graph_scope(self) -> str:
        return self._get_setting("graph_scope", "GRAPH_SCOPE", "https://graph.microsoft.com/.default")

    @property
    def data_dir(self) -> str:
        return self._get_setting("data_dir", "DATA_DIR", "data")

    @property
    def log_level(self) -> str:
        return self._get_setting("log_level", "LOG_LEVEL", "INFO")

    @property
    def gemini_api_key(self) -> str:
        return self._get_setting("gemini_api_key", "GEMINI_API_KEY", "")

    @property
    def gemini_model_name(self) -> str:
        return self._get_setting("gemini_model_name", "GEMINI_MODEL_NAME", "gemini-3.5-flash-lite")

    @classmethod
    def load(cls) -> "Settings":
        """
        Loads settings instance and triggers .env migration on first access.
        """
        migrate_and_remove_env()
        return cls()


class _LazySettings:
    """Lazy proxy that defers Settings loading until first attribute access (A-2)."""

    def __init__(self):
        self._target: Settings | None = None

    def _get_target(self) -> Settings:
        if self._target is None:
            self._target = Settings.load()
        return self._target

    def __getattr__(self, name: str):
        return getattr(self._get_target(), name)

    def reload(self) -> Settings:
        """Force re-loading of settings."""
        self._target = Settings.load()
        return self._target


# Lazy-loaded singleton instance
settings = _LazySettings()

