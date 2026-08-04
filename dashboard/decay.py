"""
Time-Decay Engine for Dashboard Signals.

Applies exponential decay to signal strengths based on cluster-specific
persistence and decay parameters.

Formula: Decayed Strength = Strength × exp(-decay_rate × days_elapsed)

Also detects "dragging issues" — signals that remain strong despite age,
indicating unresolved problems.

Adapted from the learning project's signal_generator.py.
"""

import math
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

# ─────────────────────────────────────────────────────────────────────
# DEFAULT CLUSTER DECAY PARAMETERS
# ─────────────────────────────────────────────────────────────────────

CLUSTER_DECAY_MAPPING = {
    "project_health":       {"persistence": 0.8, "decay_rate": 0.005},
    "client_relations":     {"persistence": 0.8, "decay_rate": 0.005},
    "team_dynamics":        {"persistence": 0.6, "decay_rate": 0.02},
    "delivery_risk":        {"persistence": 0.7, "decay_rate": 0.01},
    "process_compliance":   {"persistence": 0.7, "decay_rate": 0.01},
    "resource_management":  {"persistence": 0.6, "decay_rate": 0.02},
}

# Dragging issue thresholds
DRAGGING_DAYS_THRESHOLD = 3      # Minimum days for an issue to be "dragging"
DRAGGING_STRENGTH_THRESHOLD = 0.3  # Minimum decayed strength to still be concerning


# ─────────────────────────────────────────────────────────────────────
from shared.time_utils import now_ist, IST, UTC

from typing import Any

# ─────────────────────────────────────────────────────────────────────
# DATE PARSING
# ─────────────────────────────────────────────────────────────────────

def parse_date_flexible(date_str: str | None) -> datetime:
    """
    Attempts to parse varying date formats into a timezone-aware IST datetime object.
    Handles ISO formats, UTC 'Z' suffix, and common formats.
    """
    if not date_str:
        return now_ist()

    clean_date = date_str.replace(' IST', '').strip()
    if clean_date.endswith('Z'):
        clean_date = clean_date[:-1] + '+00:00'

    # Try ISO format first
    try:
        dt = datetime.fromisoformat(clean_date)
        if dt.tzinfo is None:
            dt = UTC.localize(dt)
        return dt.astimezone(IST)
    except ValueError:
        pass

    # Try common formats
    for fmt in (
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d',
        '%B %d, %Y %I:%M %p',
        '%b %d, %Y %I:%M %p',
        '%d %b %Y, %I:%M %p',
    ):
        try:
            dt = datetime.strptime(clean_date, fmt)
            return IST.localize(dt)
        except ValueError:
            continue

    return now_ist()


# ─────────────────────────────────────────────────────────────────────
# CORE DECAY CALCULATION
# ─────────────────────────────────────────────────────────────────────

def calculate_time_decay(
    strength: float,
    cluster_type: str,
    timestamp_str: str,
    persistence: float | None = None,
    decay_rate: float | None = None
) -> tuple[float, float, float]:
    """
    Applies the exponential decay formula:
        Decayed Strength = Strength × exp(-decay_rate × days_elapsed)

    Args:
        strength: Original signal strength (float)
        cluster_type: The cluster this signal belongs to
        timestamp_str: ISO timestamp of when the signal was generated
        persistence: Override persistence parameter (optional)
        decay_rate: Override decay rate parameter (optional)

    Returns:
        tuple: (decayed_strength, persistence, decay_rate)
    """
    dt = parse_date_flexible(timestamp_str)
    days_elapsed = (now_ist() - dt).days
    if days_elapsed < 0:
        days_elapsed = 0

    # Get decay params from mapping or use defaults
    if persistence is None or decay_rate is None:
        params = CLUSTER_DECAY_MAPPING.get(
            cluster_type.strip().lower(),
            {"persistence": 0.6, "decay_rate": 0.02}
        )
        if persistence is None:
            persistence = params["persistence"]
        if decay_rate is None:
            decay_rate = params["decay_rate"]

    # Calculate exponential decay
    decayed_strength = strength * math.exp(-decay_rate * days_elapsed)

    return round(decayed_strength, 4), persistence, decay_rate


# ─────────────────────────────────────────────────────────────────────
# DRAGGING ISSUE DETECTION
# ─────────────────────────────────────────────────────────────────────

def detect_dragging_issues(
    signals: list[dict[str, Any]],
    days_threshold: int | None = None,
    strength_threshold: float | None = None
) -> list[dict[str, Any]]:
    """
    Identifies signals that indicate "dragging issues" — problems that
    have persisted for multiple days without resolution.

    A signal is flagged as dragging if:
    1. It is older than `days_threshold` days
    2. Its direction is negative
    3. Its decayed strength is still above `strength_threshold`

    Args:
        signals: List of signal dicts with timestamp, decayed_strength, direction
        days_threshold: Min days to consider as dragging (default: 3)
        strength_threshold: Min decayed strength to still be concerning (default: 0.3)

    Returns:
        list: Dragging issue dicts with severity classification
    """
    if days_threshold is None:
        days_threshold = DRAGGING_DAYS_THRESHOLD
    if strength_threshold is None:
        strength_threshold = DRAGGING_STRENGTH_THRESHOLD

    dragging = []

    risk_types = {
        "delay_risk", "client_complaint", "blocker", "resource_gap",
        "escalation", "deadline_missed", "quality_issue", "dependency_blocked",
        "morale_issue", "budget_concern", "security_concern"
    }

    for sig in signals:
        # Strictly require negative direction OR explicit risk signal type
        direction = sig.get("direction", "neutral")
        sig_type = sig.get("signal_type", "").strip().lower()

        if direction == "positive":
            continue
        if direction != "negative" and sig_type not in risk_types:
            continue

        timestamp_str = sig.get("timestamp", "")
        dt = parse_date_flexible(timestamp_str)
        days_elapsed = (now_ist() - dt).days
        decayed = abs(float(sig.get("decayed_strength", 0)))

        # Dragging issues are strictly unresolved problems that have persisted across multiple days (>= days_threshold)
        if days_elapsed >= days_threshold and decayed >= strength_threshold:
            # Classify severity based on true days unresolved
            if days_elapsed >= 7 and decayed >= 0.6:
                severity = "critical"
            elif days_elapsed >= 5 or decayed >= 0.5:
                severity = "high"
            elif days_elapsed >= 3:
                severity = "medium"
            else:
                severity = "low"

            dragging.append({
                "signal_id": sig.get("signal_id", ""),
                "thread_id": sig.get("thread_id", ""),
                "event_id": sig.get("event_id", ""),
                "signal_type": sig.get("signal_type", ""),
                "cluster_type": sig.get("cluster_type", ""),
                "days_unresolved": days_elapsed,
                "original_strength": sig.get("strength", 0),
                "current_strength": decayed,
                "severity": severity,
                "summary": sig.get("event_summary", "") or sig.get("summary", ""),
                "timestamp": timestamp_str
            })

    # Sort by severity (critical first), then by days unresolved
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    dragging.sort(key=lambda x: (severity_order.get(x["severity"], 4), -x["days_unresolved"]))

    return dragging
