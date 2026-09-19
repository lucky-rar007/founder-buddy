"""
Tests for ModelRouter and quota tracking (T-2).
"""

import pytest
from datetime import datetime, timezone
from shared.model_router import (
    router,
    QuotaExhaustedError,
    _get_daily_count,
    _increment_daily_count
)


def test_select_model_default():
    """Verify default model selection for standard pipeline tasks."""
    model = router.select_model(task_type="event_extraction")
    assert model in ("gemini-3.5-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash")


def test_quota_counter_increment():
    """Verify daily counter increments in model_quota_counters table."""
    model_id = "test-model-quota-unit"
    initial_count = _get_daily_count(model_id)

    new_count = _increment_daily_count(model_id)
    assert new_count == initial_count + 1

    fetched_count = _get_daily_count(model_id)
    assert fetched_count == new_count


def test_fallback_chain_on_exhaustion(monkeypatch):
    """Verify fallback from primary to secondary model when primary quota is exhausted."""
    primary_model = "gemini-3.5-flash-lite"
    secondary_model = "gemini-2.5-flash-lite"

    # Simulate primary quota exhausted
    def mock_is_exhausted(model_id: str) -> bool:
        return model_id == primary_model

    monkeypatch.setattr("shared.model_router._is_quota_exhausted", mock_is_exhausted)

    from shared.model_router import TASK_ROUTING
    selected = router.select_model(task_type="event_extraction")
    assert selected != primary_model
    assert selected in TASK_ROUTING["event_extraction"]


def test_quota_exhausted_error_when_all_exhausted(monkeypatch):
    """Verify QuotaExhaustedError is raised when every model in chain is exhausted."""
    monkeypatch.setattr("shared.model_router._is_quota_exhausted", lambda model_id: True)

    with pytest.raises(QuotaExhaustedError):
        router.select_model(task_type="event_extraction")
