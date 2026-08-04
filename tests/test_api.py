"""
Integration tests for FastAPI server endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from shared.database import init_db

def test_health_check_endpoint(api_client):
    response = api_client.get("/health")
    assert response.status_code in [200, 503]
    data = response.json()
    assert "status" in data
    assert "version" in data
    assert "components" in data
    assert "database" in data["components"]


def test_onboarding_status_endpoint(api_client):
    response = api_client.get("/api/config/onboarding-status")
    assert response.status_code == 200
    data = response.json()
    assert "is_onboarded" in data
    assert "success" in data


def test_config_all_endpoint(api_client):
    response = api_client.get("/api/config/all")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "config" in data


def test_dashboard_stats_endpoint(api_client):
    response = api_client.get("/api/dashboard/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "stats" in data
    assert "dragging_issues" in data
    assert "actionables" in data


def test_dashboard_available_summaries_endpoint(api_client):
    response = api_client.get("/api/dashboard/summary/available?type=daily")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "periods" in data


def test_rag_status_endpoint(api_client):
    response = api_client.get("/api/rag/status")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "indexed_chunks" in data


def test_actionable_status_update(api_client):
    payload = {
        "actionable_id": "test_act_101",
        "status": "resolved"
    }
    response = api_client.post("/api/dashboard/actionable/status", json=payload)
    assert response.status_code in [200, 404]
