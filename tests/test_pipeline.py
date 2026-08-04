"""
Unit tests for Dashboard Analytics Pipeline, Issue Decay, and Savepoint logic.
"""

import pytest
from datetime import datetime, timedelta
from dashboard.decay import calculate_time_decay, detect_dragging_issues
from dashboard.registry import match_and_register_signal_type, match_and_register_cluster
from shared.database import init_db, get_db


def test_calculate_time_decay():
    now = datetime.now()
    t_fresh = now.isoformat()
    t_old = (now - timedelta(days=10)).isoformat()

    decayed_fresh, pers_fresh, rate_fresh = calculate_time_decay(
        strength=1.0, cluster_type="delivery_risk", timestamp_str=t_fresh, decay_rate=0.01
    )
    decayed_old, pers_old, rate_old = calculate_time_decay(
        strength=1.0, cluster_type="delivery_risk", timestamp_str=t_old, decay_rate=0.01
    )

    assert decayed_fresh > decayed_old
    assert round(decayed_fresh, 2) == 1.0


def test_signal_registry_fuzzy_matching():
    registry = {
        "delay_risk": {"category": "delivery", "description": "Task delay risk"},
        "client_complaint": {"category": "client_relations", "description": "Client feedback issue"}
    }

    # Exact match
    matched = match_and_register_signal_type(registry, "delay_risk", "Delay", "delivery")
    assert matched == "delay_risk"

    # Fuzzy match close name
    matched_fuzzy = match_and_register_signal_type(registry, "delay_risks", "Delays reported", "delivery")
    assert matched_fuzzy == "delay_risk"


def test_detect_dragging_issues():
    old_ts = (datetime.now() - timedelta(days=5)).isoformat()
    signals = [
        {
            "signal_id": "sig_drag_01",
            "thread_id": "th_drag_01",
            "signal_type": "blocker",
            "summary": "Hard blocker on authentication service migration.",
            "timestamp": old_ts,
            "strength": 0.9,
            "decayed_strength": 0.85
        }
    ]

    dragging = detect_dragging_issues(signals)
    assert len(dragging) >= 1
    assert dragging[0]["signal_id"] == "sig_drag_01"
    assert dragging[0]["days_unresolved"] >= 4
