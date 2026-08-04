"""
Onboarding API Routes.

Handles the initial setup wizard:
- Step 1: Azure credentials (Tenant ID, Client ID, Client Secret)
- Step 2: Gemini API key
- Step 3: Connection testing (Azure + Gemini)
- Finalize: Mark onboarding as complete
"""

from __future__ import annotations

import re
import logging
from datetime import datetime

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from shared.database import get_config, set_config, is_onboarded, get_db

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────
# REQUEST / RESPONSE MODELS
# ─────────────────────────────────────────────────────────────────────

class AzureCredentials(BaseModel):
    """Azure AD app registration credentials."""
    tenant_id: str
    client_id: str
    client_secret: str

    @field_validator("tenant_id", "client_id")
    @classmethod
    def validate_uuid_format(cls, v: str) -> str:
        v = v.strip()
        uuid_pattern = re.compile(
            r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        )
        if not uuid_pattern.match(v):
            raise ValueError("Must be a valid UUID format (e.g., 12345678-abcd-1234-abcd-123456789abc)")
        return v

    @field_validator("client_secret")
    @classmethod
    def validate_secret(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 5:
            raise ValueError("Client secret must be at least 5 characters")
        return v


class GeminiCredentials(BaseModel):
    """Gemini API key."""
    api_key: str

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) < 10:
            raise ValueError("API key must be at least 10 characters")
        if len(v) > 150:
            raise ValueError("API key is too long")
        if not re.match(r"^[a-zA-Z0-9_\-\.\/\+=]+$", v):
            raise ValueError("API key contains invalid characters")
        return v


class TestConnectionRequest(BaseModel):
    """Request to test Azure and/or Gemini connections."""
    test_azure: bool = True
    test_gemini: bool = True


# ─────────────────────────────────────────────────────────────────────
# STATUS ENDPOINT
# ─────────────────────────────────────────────────────────────────────

@router.get("/status")
async def onboarding_status():
    """
    Check whether onboarding has been completed.

    Returns the current state so the frontend knows which step to show.
    """
    completed = is_onboarded()

    has_azure = get_config("azure_tenant_id") is not None
    has_gemini = get_config("gemini_api_key") is not None

    return {
        "success": True,
        "completed": completed,
        "has_azure_credentials": has_azure,
        "has_gemini_key": has_gemini,
    }


@router.post("/reset")
async def reset_onboarding():
    """
    Clears onboarding_completed flag, allowing the user to re-run the setup wizard.
    """
    from shared.database import delete_config
    delete_config("onboarding_completed")
    logging.info("[Onboarding] Onboarding state reset. User can re-run wizard.")
    return {"success": True, "message": "Onboarding state reset. Launching setup wizard..."}


# ─────────────────────────────────────────────────────────────────────
# STEP 1: AZURE CREDENTIALS
# ─────────────────────────────────────────────────────────────────────

@router.post("/azure-credentials")
async def save_azure_credentials(creds: AzureCredentials):
    """
    Save Azure AD credentials (encrypted at rest).
    """
    try:
        set_config("azure_tenant_id", creds.tenant_id, encrypt=True)
        set_config("azure_client_id", creds.client_id, encrypt=True)
        set_config("azure_client_secret", creds.client_secret, encrypt=True)

        # Also store Graph API defaults
        set_config("graph_api_base_url", "https://graph.microsoft.com/v1.0")
        set_config("graph_scope", "https://graph.microsoft.com/.default")

        # Clear token cache so GraphClient uses newly saved credentials
        from ingestion.auth import authenticator
        authenticator.clear_cache()

        logging.info("[Onboarding] Azure credentials saved successfully.")
        return {"success": True, "message": "Azure credentials saved."}

    except Exception as e:
        logging.error(f"[Onboarding] Failed to save Azure credentials: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save credentials: {str(e)}")


# ─────────────────────────────────────────────────────────────────────
# STEP 2: GEMINI API KEY
# ─────────────────────────────────────────────────────────────────────

@router.post("/gemini-key")
async def save_gemini_key(creds: GeminiCredentials):
    """
    Save Gemini API key (encrypted at rest).
    """
    try:
        set_config("gemini_api_key", creds.api_key, encrypt=True)
        set_config("gemini_model_name", "gemini-3.5-flash-lite")

        logging.info("[Onboarding] Gemini API key saved successfully.")
        return {"success": True, "message": "Gemini API key saved."}

    except Exception as e:
        logging.error(f"[Onboarding] Failed to save Gemini key: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save Gemini key: {str(e)}")


# ─────────────────────────────────────────────────────────────────────
# STEP 3: CONNECTION TESTING
# ─────────────────────────────────────────────────────────────────────

@router.post("/test-connection")
async def test_connections(req: TestConnectionRequest):
    """
    Test Azure Graph API and Gemini API connections using stored credentials.

    Returns success/failure status for each service.
    """
    results = {
        "azure": {"tested": False, "success": False, "message": ""},
        "gemini": {"tested": False, "success": False, "message": ""},
    }

    # ─── Test Azure ──────────────────────────────────────────────
    if req.test_azure:
        results["azure"]["tested"] = True
        tenant_id = get_config("azure_tenant_id")
        client_id = get_config("azure_client_id")
        client_secret = get_config("azure_client_secret")

        if not all([tenant_id, client_id, client_secret]):
            results["azure"]["message"] = "Azure credentials not found. Please save them first."
        else:
            try:
                # Step 1: Get access token
                token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
                token_response = requests.post(
                    token_url,
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "scope": "https://graph.microsoft.com/.default",
                        "grant_type": "client_credentials",
                    },
                    timeout=15,
                )

                if token_response.status_code != 200:
                    error_data = token_response.json()
                    error_desc = error_data.get("error_description", "Authentication failed")
                    results["azure"]["message"] = f"Authentication failed: {error_desc[:200]}"
                else:
                    token = token_response.json().get("access_token")

                    # Step 2: Test Graph API call
                    org_response = requests.get(
                        "https://graph.microsoft.com/v1.0/organization",
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=15,
                    )

                    if org_response.status_code == 200:
                        org_data = org_response.json().get("value", [])
                        org_name = org_data[0].get("displayName", "Unknown") if org_data else "Unknown"
                        results["azure"]["success"] = True
                        results["azure"]["message"] = f"Connected successfully to: {org_name}"

                        # Store org name for display
                        set_config("organization_name", org_name)
                    else:
                        results["azure"]["message"] = f"Graph API call failed (HTTP {org_response.status_code}). Check API permissions."

            except requests.exceptions.Timeout:
                results["azure"]["message"] = "Connection timed out. Check your network."
            except requests.exceptions.ConnectionError:
                results["azure"]["message"] = "Could not connect to Microsoft services. Check your network."
            except Exception as e:
                results["azure"]["message"] = f"Unexpected error: {str(e)[:200]}"

    # ─── Test Gemini ─────────────────────────────────────────────
    if req.test_gemini:
        results["gemini"]["tested"] = True
        api_key = get_config("gemini_api_key")

        if not api_key:
            results["gemini"]["message"] = "Gemini API key not found. Please save it first."
        else:
            try:
                from shared.model_router import router as model_router, QuotaExhaustedError

                # Determine model from user config or ModelRouter 'test_connection' chain
                user_configured_model = get_config("gemini_model_name")
                if user_configured_model:
                    test_models = [user_configured_model, "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
                else:
                    test_models = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]

                # Deduplicate preserving order
                test_models = list(dict.fromkeys(test_models))

                last_status = None
                last_error = ""

                for model in test_models:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                    test_response = requests.post(
                        url,
                        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
                        json={
                            "contents": [{"parts": [{"text": "Reply with exactly: OK"}]}],
                            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 10},
                        },
                        timeout=15,
                    )
                    last_status = test_response.status_code

                    if test_response.status_code == 200:
                        results["gemini"]["success"] = True
                        results["gemini"]["message"] = f"Connected successfully to Gemini ({model})."
                        break
                    elif test_response.status_code == 400:
                        error_data = test_response.json()
                        last_error = error_data.get("error", {}).get("message", "Bad request")
                    elif test_response.status_code == 403:
                        last_error = "API key is invalid or has insufficient permissions."
                        break
                    elif test_response.status_code == 429:
                        last_error = "Rate limit reached (HTTP 429). Falling back to high-capacity model..."

                if not results["gemini"]["success"]:
                    if last_status == 429:
                        results["gemini"]["message"] = "API key is valid, but daily quota for testing models was reached (HTTP 429). Please wait 30 seconds before retrying."
                    elif last_error:
                        results["gemini"]["message"] = last_error
                    else:
                        results["gemini"]["message"] = f"Gemini API returned HTTP {last_status}."

            except requests.exceptions.Timeout:
                results["gemini"]["message"] = "Connection timed out. Check your network."
            except requests.exceptions.ConnectionError:
                results["gemini"]["message"] = "Could not connect to Google AI services. Check your network."
            except Exception as e:
                results["gemini"]["message"] = f"Unexpected error: {str(e)[:200]}"

    # Overall success
    all_passed = True
    if req.test_azure and not results["azure"]["success"]:
        all_passed = False
    if req.test_gemini and not results["gemini"]["success"]:
        all_passed = False

    return {
        "success": True,
        "all_passed": all_passed,
        "results": results,
    }


# ─────────────────────────────────────────────────────────────────────
# FINALIZE ONBOARDING
# ─────────────────────────────────────────────────────────────────────

@router.post("/complete")
async def complete_onboarding():
    """
    Mark onboarding as complete.

    Only succeeds if both Azure and Gemini credentials exist.
    """
    has_azure = get_config("azure_tenant_id") is not None
    has_gemini = get_config("gemini_api_key") is not None

    if not has_azure:
        raise HTTPException(status_code=400, detail="Azure credentials are required.")
    if not has_gemini:
        raise HTTPException(status_code=400, detail="Gemini API key is required.")

    set_config("onboarding_completed", datetime.now().isoformat())

    logging.info("[Onboarding] Onboarding completed successfully.")
    return {"success": True, "message": "Onboarding completed! Welcome to Founder Buddy."}


# ─────────────────────────────────────────────────────────────────────
# SETTINGS MANAGEMENT
# ─────────────────────────────────────────────────────────────────────

class UpdateSettingsRequest(BaseModel):
    tenant_id: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    gemini_api_key: str | None = None
    gemini_model_name: str | None = None
    custom_rpm: int | None = None
    custom_tpm: int | None = None
    custom_rpd: int | None = None


@router.get("/settings")
async def get_settings():
    """
    Returns current configuration settings for display in the Settings view.
    Secrets are partially masked for security.
    """
    tenant_id = get_config("azure_tenant_id") or ""
    client_id = get_config("azure_client_id") or ""
    client_secret = get_config("azure_client_secret") or ""
    gemini_api_key = get_config("gemini_api_key") or ""
    gemini_model = get_config("gemini_model_name") or "gemini-3.5-flash-lite"

    custom_rpm = get_config("custom_rpm")
    custom_tpm = get_config("custom_tpm")
    custom_rpd = get_config("custom_rpd")

    def mask(s: str) -> str:
        if not s or len(s) < 8:
            return "••••••••"
        return s[:4] + "••••••••" + s[-4:]

    return {
        "success": True,
        "settings": {
            "tenant_id": tenant_id,
            "client_id": client_id,
            "client_secret_masked": mask(client_secret),
            "gemini_api_key_masked": mask(gemini_api_key),
            "gemini_model_name": gemini_model,
            "has_client_secret": bool(client_secret),
            "has_gemini_key": bool(gemini_api_key),
            "custom_rpm": int(custom_rpm) if custom_rpm else 15,
            "custom_tpm": int(custom_tpm) if custom_tpm else 250000,
            "custom_rpd": int(custom_rpd) if custom_rpd else 500,
        }
    }


@router.post("/settings")
async def update_settings(req: UpdateSettingsRequest):
    """
    Updates configuration settings in SQLite with Fernet encryption.
    """
    if req.tenant_id and req.tenant_id.strip():
        set_config("azure_tenant_id", req.tenant_id.strip())

    if req.client_id and req.client_id.strip():
        set_config("azure_client_id", req.client_id.strip())

    if req.client_secret and req.client_secret.strip() and "•" not in req.client_secret:
        set_config("azure_client_secret", req.client_secret.strip(), encrypt=True)

    if req.gemini_api_key and req.gemini_api_key.strip() and "•" not in req.gemini_api_key:
        set_config("gemini_api_key", req.gemini_api_key.strip(), encrypt=True)

    if req.gemini_model_name and req.gemini_model_name.strip():
        set_config("gemini_model_name", req.gemini_model_name.strip())

    if req.custom_rpm is not None:
        set_config("custom_rpm", str(req.custom_rpm))

    if req.custom_tpm is not None:
        set_config("custom_tpm", str(req.custom_tpm))

    if req.custom_rpd is not None:
        set_config("custom_rpd", str(req.custom_rpd))

    logging.info("[Settings] Configuration settings updated via Settings UI.")
    return {"success": True, "message": "Settings updated successfully."}


class SystemResetRequest(BaseModel):
    confirmation: str


@router.post("/system/reset")
async def system_reset(req: SystemResetRequest):
    """
    Permanently wipes all credentials, databases, vector stores, and cached state.
    Requires payload: {"confirmation": "YES"}
    """
    if not req.confirmation or req.confirmation.strip().upper() != "YES":
        raise HTTPException(
            status_code=400,
            detail="Confirmation string 'YES' is required to perform a system reset."
        )

    try:
        from main import wipe_all_data
        from dashboard.db import init_db
        from ingestion.auth import authenticator

        logging.info("[System Reset] Full clean slate reset requested by user.")
        wipe_all_data()
        init_db()
        authenticator.clear_cache()

        return {
            "success": True,
            "message": "System reset completed successfully. All data wiped."
        }
    except Exception as e:
        logging.error(f"[System Reset] Failed to wipe data: {e}")
        raise HTTPException(status_code=500, detail=f"System reset failed: {str(e)}")

