"""
Configuration API Routes.

Provides CRUD endpoints for application settings.
Sensitive values are returned masked; updates are encrypted at rest.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from shared.database import get_config, set_config, get_all_config, is_onboarded

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────────────────────────────

class ConfigUpdateRequest(BaseModel):
    """Request to update a config value."""
    key: str
    value: str
    encrypt: bool = False


# ─────────────────────────────────────────────────────────────────────
# SENSITIVE KEYS (masked in responses)
# ─────────────────────────────────────────────────────────────────────

_SENSITIVE_KEYS = {
    "azure_client_secret",
    "gemini_api_key",
}

_PARTIALLY_MASKED_KEYS = {
    "azure_tenant_id",
    "azure_client_id",
}


def _mask_value(key: str, value: str) -> str:
    """Mask sensitive config values for display."""
    if key in _SENSITIVE_KEYS:
        if len(value) <= 6:
            return "●" * len(value)
        return value[:3] + "●" * (len(value) - 6) + value[-3:]

    if key in _PARTIALLY_MASKED_KEYS:
        if len(value) <= 8:
            return value[:2] + "●" * (len(value) - 2)
        return value[:4] + "●" * (len(value) - 8) + value[-4:]

    return value


# ─────────────────────────────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────────────────────────────

@router.get("/all")
async def get_all_settings():
    """
    Get all configuration values.

    Sensitive values are masked for security.
    """
    config = get_all_config()

    masked_config = {}
    for key, value in config.items():
        masked_config[key] = {
            "value": _mask_value(key, value),
            "is_sensitive": key in _SENSITIVE_KEYS or key in _PARTIALLY_MASKED_KEYS,
        }

    return {
        "success": True,
        "config": masked_config,
        "is_onboarded": is_onboarded(),
    }


@router.get("/get/{key}")
async def get_setting(key: str):
    """
    Get a single config value by key.

    Sensitive values are masked.
    """
    value = get_config(key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found.")

    return {
        "success": True,
        "key": key,
        "value": _mask_value(key, value),
        "is_sensitive": key in _SENSITIVE_KEYS or key in _PARTIALLY_MASKED_KEYS,
    }


@router.post("/set")
async def update_setting(req: ConfigUpdateRequest):
    """
    Set or update a config value.

    If encrypt=True, the value is encrypted at rest.
    Only whitelisted keys can be modified via this endpoint.
    """
    # Whitelist of keys that can be safely modified via the settings UI
    _ALLOWED_WRITABLE_KEYS = {
        "preferred_sync_time", "gemini_model_name", "outlook_user_id",
        "ingestion_date_range", "log_level",
        # Sensitive keys are allowed but must use encrypt=True
        "azure_tenant_id", "azure_client_id", "azure_client_secret",
        "gemini_api_key",
    }

    if req.key not in _ALLOWED_WRITABLE_KEYS:
        raise HTTPException(
            status_code=403,
            detail=f"Config key '{req.key}' cannot be modified via this endpoint."
        )

    if req.key == "preferred_sync_time":
        import re
        if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", req.value):
            raise HTTPException(
                status_code=400,
                detail="Preferred sync time must be in 24-hour HH:MM format (e.g. 02:00 or 23:30)."
            )

    try:
        set_config(req.key, req.value, encrypt=req.encrypt)
        logging.info(f"[Config] Updated config key: {req.key}")
        return {
            "success": True,
            "message": f"Config '{req.key}' updated successfully.",
        }
    except Exception as e:
        logging.error(f"[Config] Failed to update '{req.key}': {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update config: {str(e)}")


@router.get("/onboarding-status")
async def check_onboarding():
    """Quick check if onboarding is completed."""
    return {
        "success": True,
        "is_onboarded": is_onboarded(),
        "organization_name": get_config("organization_name") or "",
    }
