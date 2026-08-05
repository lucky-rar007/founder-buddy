"""
Evidence & Provenance Pricing Engine for Dashboard Signals.

Replaces LLM self-graded confidence scores with a deterministic evidence rule ledger.
Evaluates observed structural evidence markers from threads and messages.

Formula:
  Evidence Score = sum(marker_weights) clamped to [0.1, 1.0]

Bands:
  - VERIFIED_RISK (Score >= 0.7): Strong verified signal.
  - PROBABLE_SIGNAL (0.4 <= Score < 0.7): Moderate risk signal for review.
  - NEEDS_EVIDENCE (Score < 0.4): Low-evidence marker.
"""

from __future__ import annotations

import re
from typing import Any

# ─────────────────────────────────────────────────────────────────────
# EVIDENCE MARKERS & WEIGHTS
# ─────────────────────────────────────────────────────────────────────

EVIDENCE_MARKER_WEIGHTS = {
    "explicit_keyword_match": 0.35,     # Matches explicit risk terms (blocker, urgent, delay, bug)
    "external_client_sender": 0.30,     # Sent by external client or partner domain
    "multi_party_discussion": 0.20,     # >2 participants active in thread
    "unresolved_interrogation": 0.20,   # Contains unresolved questions or callouts
    "urgent_syntax_emphasis": 0.15,     # Exclamations, ALL-CAPS words, high urgency phrasing
    "leadership_participant": 0.15,     # Founder/Executive involved in thread
}

URGENT_KEYWORDS = re.compile(
    r"\b(blocked|blocker|outage|delay|delayed|client complaint|escalate|escalated|bug|regression|failure|vulnerability|churn|resignation|deadline missed)\b",
    re.IGNORECASE
)

URGENT_SYNTAX = re.compile(
    r"(\bASAP\b|\bURGENT\b|\bCRITICAL\b|!{2,}|\bBROKEN\b)",
    re.IGNORECASE
)


def evaluate_evidence_strength(
    event_summary: str,
    raw_text: str | None = None,
    participants: str | list[str] | None = None,
    message_count: int = 1,
    source: str = "teams"
) -> dict[str, Any]:
    """
    Evaluates evidence markers for an extracted event or thread.

    Returns dict with:
      - evidence_score (float 0.1 - 1.0)
      - evidence_band ('VERIFIED_RISK', 'PROBABLE_SIGNAL', 'NEEDS_EVIDENCE')
      - observed_markers (list of marker keys found)
    """
    observed_markers = []
    text_content = f"{event_summary} {raw_text or ''}"

    # Marker 1: Explicit Keyword Match
    if URGENT_KEYWORDS.search(text_content):
        observed_markers.append("explicit_keyword_match")

    # Marker 2: Multi-party discussion
    participant_count = 1
    if isinstance(participants, list):
        participant_count = len(participants)
    elif isinstance(participants, str) and participants:
        participant_count = len([p for p in participants.split(",") if p.strip()])
    if participant_count > 2 or message_count > 3:
        observed_markers.append("multi_party_discussion")

    # Marker 3: Unresolved interrogation (questions or calls to action)
    if "?" in text_content or "who is" in text_content.lower() or "status on" in text_content.lower():
        observed_markers.append("unresolved_interrogation")

    # Marker 4: Urgent Syntax Emphasis
    if URGENT_SYNTAX.search(text_content):
        observed_markers.append("urgent_syntax_emphasis")

    # Marker 5: External Client Sender
    if source == "outlook" or "@" in (raw_text or ""):
        # Check if external domain non-internal
        if "client" in text_content.lower() or "customer" in text_content.lower():
            observed_markers.append("external_client_sender")

    # Calculate evidence score
    base_score = 0.20  # Baseline observation score
    for marker in observed_markers:
        base_score += EVIDENCE_MARKER_WEIGHTS.get(marker, 0.10)

    evidence_score = round(min(1.0, max(0.10, base_score)), 2)

    if evidence_score >= 0.70:
        band = "VERIFIED_RISK"
    elif evidence_score >= 0.40:
        band = "PROBABLE_SIGNAL"
    else:
        band = "NEEDS_EVIDENCE"

    return {
        "evidence_score": evidence_score,
        "evidence_band": band,
        "observed_markers": observed_markers
    }
