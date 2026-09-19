"""
Integration tests for the complete onboarding flow (T-4).
"""

import pytest


def test_complete_onboarding_flow(api_client, mock_gemini_api, mock_graph_api, monkeypatch):
    """End-to-end integration test of the onboarding wizard."""
    # Mock network calls during connection testing
    monkeypatch.setattr("requests.post", lambda *args, **kwargs: type("Response", (), {
        "status_code": 200,
        "json": lambda self: {"access_token": "mock_token", "expires_in": 3600, "candidates": [{"content": {"parts": [{"text": "OK"}]}}]},
        "text": "OK",
        "raise_for_status": lambda self: None
    })())

    # 1. Check initial status
    res = api_client.get("/api/onboarding/status")
    assert res.status_code == 200

    # 2. Save Azure credentials
    azure_payload = {
        "tenant_id": "11111111-2222-3333-4444-555555555555",
        "client_id": "66666666-7777-8888-9999-000000000000",
        "client_secret": "my-mock-azure-client-secret-value-12345"
    }
    res = api_client.post("/api/onboarding/azure-credentials", json=azure_payload)
    assert res.status_code == 200
    assert res.json()["success"] is True

    # 3. Save Gemini key
    gemini_payload = {
        "api_key": "AIzaSy_mock_test_key_for_onboarding_flow"
    }
    res = api_client.post("/api/onboarding/gemini-key", json=gemini_payload)
    assert res.status_code == 200
    assert res.json()["success"] is True

    # 4. Test connections
    res = api_client.post("/api/onboarding/test-connection", json={"test_azure": False, "test_gemini": True})
    assert res.status_code == 200

    # 5. Complete onboarding
    res = api_client.post("/api/onboarding/complete")
    assert res.status_code == 200
    assert res.json()["success"] is True

    # 6. Verify status now reports onboarded
    res = api_client.get("/api/onboarding/status")
    assert res.status_code == 200
    assert res.json()["completed"] is True


def test_system_reset_safety_gate(api_client):
    """Verify system reset rejects missing or wrong confirmation."""
    # Invalid confirmation
    res = api_client.post("/api/onboarding/system/reset", json={"confirmation": "NO"})
    assert res.status_code == 400

    # Valid safety confirmation
    res = api_client.post("/api/onboarding/system/reset", json={"confirmation": "RESET_ALL_DATA_CONFIRMED"})
    assert res.status_code == 200
    assert res.json()["success"] is True
