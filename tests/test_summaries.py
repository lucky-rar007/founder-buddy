"""
Unit tests for Dashboard Summaries & Prompt Compilation module.
"""

import pytest
import json
import re
from dashboard.summaries import load_prompt_template, SummaryEngine


def test_load_prompt_template():
    daily_prompt = load_prompt_template("daily_summary_prompt.txt")
    assert daily_prompt is not None
    assert len(daily_prompt) > 0

    weekly_prompt = load_prompt_template("weekly_summary_prompt.txt")
    assert weekly_prompt is not None
    assert len(weekly_prompt) > 0


def test_summary_engine_formatters():
    dirty_json = "```json\n{\"ai_executive_summary\": \"All systems operational.\", \"top_issues\": []}\n```"
    cleaned = re.sub(r"```json|```", "", dirty_json).strip()
    parsed = json.loads(cleaned)

    assert parsed["ai_executive_summary"] == "All systems operational."
    assert parsed["top_issues"] == []


def test_empty_period_summary_handling():
    engine = SummaryEngine()
    
    # Test empty daily summary
    daily = engine.generate_daily_summary("2099-01-01")
    assert daily is not None
    assert "Not enough data to generate summary for 2099-01-01" in daily["content_markdown"]

    # Test empty weekly summary
    weekly = engine.generate_weekly_summary("2099-01-05", "2099-01-11")
    assert weekly is not None
    assert "Not enough data to generate summary for 2099-01-05 to 2099-01-11" in weekly["content_markdown"]

    # Test empty monthly summary
    monthly = engine.generate_monthly_summary("2099-01-01", "2099-01-31")
    assert monthly is not None
    assert "Not enough data to generate summary for 2099-01-01 to 2099-01-31" in monthly["content_markdown"]


def test_update_all_active_summaries():
    engine = SummaryEngine()
    engine.update_all_active_summaries("2026-08-04")
    
    from dashboard.db import get_summary
    daily = get_summary("daily", "2026-08-04", "2026-08-04")
    assert daily is not None
    
    weekly = get_summary("weekly", "2026-08-03", "2026-08-09")
    assert weekly is not None

    monthly = get_summary("monthly", "2026-08-01", "2026-08-31")
    assert monthly is not None
