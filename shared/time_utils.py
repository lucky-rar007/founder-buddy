"""
IST (India Standard Time) utility functions.

Centralizes all timezone-aware datetime operations
using pytz for consistent IST timestamps across the pipeline.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import pytz

IST = pytz.timezone("Asia/Kolkata")
UTC = pytz.utc


def get_current_ist_time() -> str:
    """
    Return current IST time as ISO 8601 string.

    Returns:
        ISO formatted string: '2024-01-15T07:00:00+05:30'
    """
    now_ist = datetime.now(IST)
    return now_ist.isoformat()


def convert_utc_to_ist(timestamp: Optional[str]) -> Optional[str]:
    """
    Convert a UTC ISO timestamp string to IST ISO string.

    Handles both 'Z'-suffixed and '+00:00'-suffixed UTC strings.
    Returns None if input is None or unparseable.

    Args:
        timestamp: UTC ISO string e.g. '2024-01-15T01:30:00Z'

    Returns:
        IST ISO string e.g. '2024-01-15T07:00:00+05:30' or None
    """
    if not timestamp:
        return None

    try:
        # Normalise the Z suffix
        normalised = timestamp.replace("Z", "+00:00")
        dt_utc = datetime.fromisoformat(normalised)

        # Attach UTC zone if naïve
        if dt_utc.tzinfo is None:
            dt_utc = UTC.localize(dt_utc)

        dt_ist = dt_utc.astimezone(IST)
        return dt_ist.isoformat()

    except (ValueError, AttributeError):
        return timestamp  # Return original if unparseable


def now_ist() -> datetime:
    """
    Return current IST datetime object (timezone-aware).
    """
    return datetime.now(IST)


def format_ist_for_display(timestamp: Optional[str]) -> str:
    """
    Format an ISO timestamp for human-readable display in IST.

    Args:
        timestamp: Any ISO timestamp string

    Returns:
        Human-readable string like '15 Jan 2024, 07:00 AM IST'
    """
    if not timestamp:
        return "—"

    try:
        normalised = timestamp.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalised)
        if dt.tzinfo is None:
            dt = UTC.localize(dt)
        dt_ist = dt.astimezone(IST)
        return dt_ist.strftime("%d %b %Y, %I:%M %p IST")
    except (ValueError, AttributeError):
        return timestamp
