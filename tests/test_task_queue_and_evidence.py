"""
Unit tests for Task Queue, Evidence Engine, and Dragging Issues Rechecks.
"""

import pytest
from shared.database import init_db, get_db
from shared.task_queue import (
    enqueue_task,
    claim_due_tasks,
    complete_task,
    fail_task,
    register_task_handler,
    process_queue_lane
)
from dashboard.evidence import evaluate_evidence_strength
from dashboard.decay import detect_dragging_issues


@pytest.fixture(autouse=True)
def setup_test_db():
    init_db()
    with get_db() as conn:
        conn.execute("DELETE FROM agent_tasks")
        conn.execute("DELETE FROM dragging_issues")


def test_task_queue_enqueue_and_claim():
    task_id = enqueue_task("fast_text_clean", {"thread_id": "th_123"}, lane="fast", priority=150)
    assert task_id.startswith("task_")

    claimed = claim_due_tasks(lane="fast", limit=5)
    assert len(claimed) == 1
    assert claimed[0]["task_id"] == task_id
    assert claimed[0]["kind"] == "fast_text_clean"
    assert claimed[0]["payload"]["thread_id"] == "th_123"

    complete_task(task_id)

    # Claiming again should yield no tasks
    claimed_again = claim_due_tasks(lane="fast", limit=5)
    assert len(claimed_again) == 0


def test_task_queue_process():
    executed_payloads = []

    def mock_handler(payload):
        executed_payloads.append(payload)

    register_task_handler("mock_kind", mock_handler)
    enqueue_task("mock_kind", {"item": "apple"}, lane="analytics", priority=100)

    count = process_queue_lane("analytics", limit=10)
    assert count == 1
    assert len(executed_payloads) == 1
    assert executed_payloads[0]["item"] == "apple"


def test_evidence_pricing_engine():
    # High evidence (keyword + unresolved question + multi-party)
    res_high = evaluate_evidence_strength(
        event_summary="Urgent blocker delay on database migration?",
        raw_text="Team is blocked and waiting on vendor status?",
        participants="alice@co.com, bob@co.com, charlie@co.com",
        message_count=5,
        source="outlook"
    )
    assert res_high["evidence_score"] >= 0.70
    assert res_high["evidence_band"] == "VERIFIED_RISK"
    assert "explicit_keyword_match" in res_high["observed_markers"]

    # Low evidence
    res_low = evaluate_evidence_strength(
        event_summary="Discussion on lunch plans",
        raw_text="See you tomorrow",
        participants="alice@co.com",
        message_count=1,
        source="teams"
    )
    assert res_low["evidence_score"] < 0.40
    assert res_low["evidence_band"] == "NEEDS_EVIDENCE"


def test_dragging_issues_recheck_window():
    import datetime
    future_recheck = (datetime.datetime.now() + datetime.timedelta(days=3)).isoformat()

    signals = [
        {
            "signal_id": "sig_001",
            "thread_id": "th_001",
            "signal_type": "blocker",
            "direction": "negative",
            "decayed_strength": 0.8,
            "timestamp": "2026-08-01T10:00:00Z",
            "recheck_after": future_recheck
        },
        {
            "signal_id": "sig_002",
            "thread_id": "th_002",
            "signal_type": "blocker",
            "direction": "negative",
            "decayed_strength": 0.8,
            "timestamp": "2026-08-01T10:00:00Z",
            "recheck_after": None
        }
    ]

    dragging = detect_dragging_issues(signals, days_threshold=2, strength_threshold=0.3)
    # sig_001 should be skipped due to future recheck_after window
    assert len(dragging) == 1
    assert dragging[0]["signal_id"] == "sig_002"
