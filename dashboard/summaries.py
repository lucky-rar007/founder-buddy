"""
Summary Generation Engine.

Synthesizes daily, weekly, and monthly signals, events, and metrics
into structured executive briefings using Gemini.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from shared.database import get_db, get_config
from dashboard.db import add_summary, get_summary
from shared.gemini_client import query_gemini_api, load_prompt_template, clean_json_text

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent


def get_week_range(date_str: str) -> tuple[str, str]:
    """Calculate Monday to Sunday YYYY-MM-DD date range for a given date."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    start = dt - timedelta(days=dt.weekday())
    end = start + timedelta(days=6)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def get_month_range(date_str: str) -> tuple[str, str]:
    """Calculate 1st day to last day YYYY-MM-DD date range for a given date's month."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    start = dt.replace(day=1)
    if dt.month == 12:
        next_month = dt.replace(year=dt.year + 1, month=1, day=1)
    else:
        next_month = dt.replace(month=dt.month + 1, day=1)
    end = next_month - timedelta(days=1)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


class SummaryEngine:
    """
    Synthesizes signals, events, and health metrics into daily, weekly, and monthly scorecards.
    """

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or get_config("gemini_api_key")

    def _query_day_metrics(self, date_str: str) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
        """Query events, signals, actionables for date_str, plus active open actionables and dragging issues across workspace."""
        events = []
        signals = []
        actionables = []
        open_actionables = []
        dragging_issues = []

        with get_db() as conn:
            # Events
            rows = conn.execute(
                """SELECT events.* FROM events
                   LEFT JOIN threads ON events.thread_id = threads.thread_id
                   WHERE threads.thread_date = ? OR events.timestamp LIKE ?""", (date_str, f"{date_str}%")
            ).fetchall()
            events = [dict(r) for r in rows]

            # Signals
            rows = conn.execute(
                """SELECT signals.* FROM signals
                   LEFT JOIN threads ON signals.thread_id = threads.thread_id
                   WHERE threads.thread_date = ? OR signals.timestamp LIKE ?""", (date_str, f"{date_str}%")
            ).fetchall()
            signals = [dict(r) for r in rows]

            # Actionables on date
            rows = conn.execute(
                """SELECT actionables.* FROM actionables
                   LEFT JOIN threads ON actionables.thread_id = threads.thread_id
                   WHERE threads.thread_date = ? OR actionables.created_at LIKE ?""", (date_str, f"{date_str}%")
            ).fetchall()
            actionables = [dict(r) for r in rows]

            # Active open actionables in workspace
            rows = conn.execute(
                """SELECT * FROM actionables WHERE status IN ('open', 'in_progress') ORDER BY created_at DESC LIMIT 50"""
            ).fetchall()
            open_actionables = [dict(r) for r in rows]

            # Active dragging issues
            rows = conn.execute(
                """SELECT * FROM dragging_issues WHERE status IN ('active', 'open', 'in_progress') ORDER BY days_unresolved DESC LIMIT 50"""
            ).fetchall()
            dragging_issues = [dict(r) for r in rows]

        return events, signals, actionables, open_actionables, dragging_issues

    def _query_period_metrics(self, start_date: str, end_date: str) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
        """Query events, signals, actionables across date range start_date to end_date."""
        events = []
        signals = []
        actionables = []
        open_actionables = []
        dragging_issues = []

        with get_db() as conn:
            rows = conn.execute(
                """SELECT events.* FROM events
                   LEFT JOIN threads ON events.thread_id = threads.thread_id
                   WHERE (threads.thread_date >= ? AND threads.thread_date <= ?)
                      OR (events.timestamp >= ? AND events.timestamp <= ? || 'T23:59:59')""",
                (start_date, end_date, start_date, end_date)
            ).fetchall()
            events = [dict(r) for r in rows]

            rows = conn.execute(
                """SELECT signals.* FROM signals
                   LEFT JOIN threads ON signals.thread_id = threads.thread_id
                   WHERE (threads.thread_date >= ? AND threads.thread_date <= ?)
                      OR (signals.timestamp >= ? AND signals.timestamp <= ? || 'T23:59:59')""",
                (start_date, end_date, start_date, end_date)
            ).fetchall()
            signals = [dict(r) for r in rows]

            rows = conn.execute(
                """SELECT actionables.* FROM actionables
                   LEFT JOIN threads ON actionables.thread_id = threads.thread_id
                   WHERE (threads.thread_date >= ? AND threads.thread_date <= ?)
                      OR (actionables.created_at >= ? AND actionables.created_at <= ? || 'T23:59:59')""",
                (start_date, end_date, start_date, end_date)
            ).fetchall()
            actionables = [dict(r) for r in rows]

            rows = conn.execute(
                """SELECT * FROM actionables WHERE status IN ('open', 'in_progress') ORDER BY created_at DESC LIMIT 50"""
            ).fetchall()
            open_actionables = [dict(r) for r in rows]

            rows = conn.execute(
                """SELECT * FROM dragging_issues WHERE status IN ('active', 'open', 'in_progress') ORDER BY days_unresolved DESC LIMIT 50"""
            ).fetchall()
            dragging_issues = [dict(r) for r in rows]

        return events, signals, actionables, open_actionables, dragging_issues

    def _calc_dynamic_health(self, open_actionables: list[dict], dragging_issues: list[dict]):
        """Compute cluster health index from open actionables & dragging issues."""
        clusters = {
            "project_health": {"score": 100, "trend": "stable"},
            "client_relations": {"score": 100, "trend": "stable"},
            "team_dynamics": {"score": 100, "trend": "stable"},
            "delivery_risk": {"score": 100, "trend": "stable"},
            "process_compliance": {"score": 100, "trend": "stable"},
            "resource_management": {"score": 100, "trend": "stable"}
        }
        prio_weights = {"blocker": 25, "critical": 25, "high": 15, "medium": 10, "low": 5, "info": 5}
        
        all_open = open_actionables + dragging_issues
        for item in all_open:
            prio = (item.get("priority") or item.get("severity") or "medium").lower()
            deduction = prio_weights.get(prio, 10)
            title = (item.get("title") or "").lower()
            c_key = "delivery_risk"
            if "client" in title or "external" in title:
                c_key = "client_relations"
            elif "team" in title or "people" in title:
                c_key = "team_dynamics"
            elif "resource" in title or "cost" in title:
                c_key = "resource_management"
            elif "process" in title or "compliance" in title:
                c_key = "process_compliance"
            elif "project" in title or "feature" in title:
                c_key = "project_health"

            current = clusters[c_key]["score"]
            new_score = max(20, current - deduction)
            clusters[c_key]["score"] = new_score
            if new_score < 40 or prio in ("critical", "blocker"):
                clusters[c_key]["trend"] = "declining"
            elif new_score < 75:
                clusters[c_key]["trend"] = "declining"
        return clusters

    # ─── Daily Summary Generation ──────────────────────────────
    
    def generate_daily_summary(self, date_str: str, pipeline_run_id: str | None = None) -> dict | None:
        """
        Generate and save a daily summary for a specific date YYYY-MM-DD.
        """
        logging.info(f"[SummaryEngine] Compiling daily summary for: {date_str}")
        events, signals, actionables, open_actionables, dragging_issues = self._query_day_metrics(date_str)
        cluster_health = self._calc_dynamic_health(open_actionables, dragging_issues)

        # Check if there's any data logged on this specific day
        if not events and not signals and not actionables:
            brief_text = f"Not enough data to generate summary for {date_str}"
            highlights_text = f"• Not enough data to generate summary for {date_str}"
            
            summary = {
                "summary_id": f"sum_daily_{date_str}",
                "summary_type": "daily",
                "period_start": date_str,
                "period_end": date_str,
                "title": f"Daily Summary — {date_str}",
                "content_json": json.dumps({
                    "top_issues": [],
                    "new_actionables": 0,
                    "resolved_actionables": 0,
                    "dragging_issues": [
                        {"title": d.get("title"), "days": d.get("days_unresolved", 1), "severity": d.get("severity", "medium")}
                        for d in dragging_issues[:5]
                    ],
                    "cluster_health": cluster_health,
                    "key_highlights": highlights_text,
                    "ai_executive_summary": brief_text,
                    "not_enough_data": True
                }),
                "content_markdown": f"### Daily Summary — {date_str}\n\n**Brief:** {brief_text}\n\n**Key Highlights:**\n{highlights_text}",
                "stats_json": json.dumps({
                    "total_events": 0,
                    "total_signals": 0,
                    "total_actionables": len(open_actionables)
                }),
                "pipeline_run_id": pipeline_run_id
            }
            add_summary(summary)
            return summary

        if not self.api_key:
            # Fallback if Gemini key is not set
            brief_text = f"Daily summary generated for {date_str} with {len(events)} event(s) and {len(signals)} signal(s)."
            highlights_text = f"• Processed {len(events)} events and {len(signals)} signals on {date_str}."
            summary = {
                "summary_id": f"sum_daily_{date_str}",
                "summary_type": "daily",
                "period_start": date_str,
                "period_end": date_str,
                "title": f"Daily Summary — {date_str}",
                "content_json": json.dumps({
                    "top_issues": [],
                    "new_actionables": len(actionables),
                    "resolved_actionables": sum(1 for a in actionables if a.get("status") in ("resolved", "dismissed")),
                    "dragging_issues": [],
                    "cluster_health": cluster_health,
                    "key_highlights": highlights_text,
                    "ai_executive_summary": brief_text
                }),
                "content_markdown": f"### Daily Summary — {date_str}\n\n**Brief:** {brief_text}\n\n**Key Highlights:**\n{highlights_text}",
                "stats_json": json.dumps({
                    "total_events": len(events),
                    "total_signals": len(signals),
                    "total_actionables": len(actionables)
                }),
                "pipeline_run_id": pipeline_run_id
            }
            add_summary(summary)
            return summary

        try:
            template = load_prompt_template("daily_summary_prompt.txt")
        except Exception:
            path = Path(__file__).resolve().parent / "prompts" / "daily_summary_prompt.txt"
            template = path.read_text(encoding="utf-8")

        combined_actionables = actionables + open_actionables + dragging_issues
        prompt = template.replace("{target_date}", date_str)\
                         .replace("{events_json}", json.dumps(events, indent=2))\
                         .replace("{signals_json}", json.dumps(signals, indent=2))\
                         .replace("{actionables_json}", json.dumps(combined_actionables, indent=2))

        try:
            response_str = query_gemini_api(prompt, api_key=self.api_key)
            if response_str.startswith("```"):
                lines = response_str.splitlines()
                if lines[0].startswith("```json") or lines[0].startswith("```"):
                    response_str = "\n".join(lines[1:-1])
            
            content = json.loads(response_str)

            markdown_brief = f"### Daily Summary — {date_str}\n\n"
            markdown_brief += f"**Brief:** {content.get('ai_executive_summary', '')}\n\n"
            markdown_brief += "**Key Highlights:**\n" + content.get("key_highlights", "")

            summary = {
                "summary_id": f"sum_daily_{date_str}",
                "summary_type": "daily",
                "period_start": date_str,
                "period_end": date_str,
                "title": f"Daily Summary — {date_str}",
                "content_json": json.dumps(content),
                "content_markdown": markdown_brief,
                "stats_json": json.dumps({
                    "total_events": len(events),
                    "total_signals": len(signals),
                    "total_actionables": len(actionables)
                }),
                "pipeline_run_id": pipeline_run_id
            }

            add_summary(summary)
            logging.info(f"[SummaryEngine] Successfully generated daily summary for {date_str}")
            return summary

        except Exception as e:
            logging.error(f"[SummaryEngine] Failed to generate daily summary for {date_str}: {e}")
            return None

    # ─── Weekly Summary Generation ─────────────────────────────
    
    def generate_weekly_summary(self, start_date: str, end_date: str, pipeline_run_id: str | None = None) -> dict | None:
        """
        Generate and save a weekly scorecard aggregating daily summaries and raw period metrics.
        """
        logging.info(f"[SummaryEngine] Compiling weekly scorecard from {start_date} to {end_date}")
        
        # 1. Query existing daily summaries in week date range
        dailies = []
        with get_db() as conn:
            rows = conn.execute(
                """SELECT * FROM summaries
                   WHERE summary_type = 'daily' AND period_start >= ? AND period_end <= ?
                   ORDER BY period_start ASC""",
                (start_date, end_date)
            ).fetchall()
            dailies = [dict(r) for r in rows]

        # 2. Query raw period metrics in case daily summaries haven't been computed
        events, signals, actionables, open_actionables, dragging_issues = self._query_period_metrics(start_date, end_date)
        cluster_health = self._calc_dynamic_health(open_actionables, dragging_issues)

        has_active_dailies = any(
            not json.loads(d.get("content_json", "{}")).get("not_enough_data", False)
            for d in dailies if d.get("content_json")
        )

        if not has_active_dailies and not events and not signals and not actionables:
            brief_text = f"Not enough data to generate summary for {start_date} to {end_date}"
            highlights_text = f"• Not enough data to generate summary for {start_date} to {end_date}"

            summary = {
                "summary_id": f"sum_weekly_{start_date}_{end_date}",
                "summary_type": "weekly",
                "period_start": start_date,
                "period_end": end_date,
                "title": f"Weekly Scorecard — {start_date} to {end_date}",
                "content_json": json.dumps({
                    "top_issues": [],
                    "new_actionables": 0,
                    "resolved_actionables": 0,
                    "cluster_health": cluster_health,
                    "key_highlights": highlights_text,
                    "ai_executive_summary": brief_text,
                    "not_enough_data": True
                }),
                "content_markdown": f"### Weekly Scorecard — {start_date} to {end_date}\n\n**Brief:** {brief_text}\n\n**Weekly Highlights:**\n{highlights_text}",
                "stats_json": json.dumps({"days_covered": 0}),
                "pipeline_run_id": pipeline_run_id
            }
            add_summary(summary)
            return summary

        # Extract daily summary contents or generate fallback synthesis
        dailies_data = []
        for d in dailies:
            try:
                dailies_data.append({
                    "date": d["period_start"],
                    "summary": json.loads(d["content_json"])
                })
            except Exception:
                pass

        if not self.api_key:
            brief_text = f"Weekly scorecard for period {start_date} to {end_date} compiled from workspace communications."
            highlights_text = f"• Total Events: {len(events)}\n• Total Signals: {len(signals)}\n• Actionables Created: {len(actionables)}"
            summary = {
                "summary_id": f"sum_weekly_{start_date}_{end_date}",
                "summary_type": "weekly",
                "period_start": start_date,
                "period_end": end_date,
                "title": f"Weekly Scorecard — {start_date} to {end_date}",
                "content_json": json.dumps({
                    "top_issues": [],
                    "new_actionables": len(actionables),
                    "resolved_actionables": sum(1 for a in actionables if a.get("status") in ("resolved", "dismissed")),
                    "cluster_health": cluster_health,
                    "key_highlights": highlights_text,
                    "ai_executive_summary": brief_text
                }),
                "content_markdown": f"### Weekly Scorecard — {start_date} to {end_date}\n\n**Brief:** {brief_text}\n\n**Weekly Highlights:**\n{highlights_text}",
                "stats_json": json.dumps({"days_covered": len(dailies)}),
                "pipeline_run_id": pipeline_run_id
            }
            add_summary(summary)
            return summary

        try:
            try:
                template = load_prompt_template("weekly_summary_prompt.txt")
            except Exception:
                path = Path(__file__).resolve().parent / "prompts" / "weekly_summary_prompt.txt"
                template = path.read_text(encoding="utf-8")

            # Fallback data payload if no daily summaries exist
            if not dailies_data:
                dailies_data = [{
                    "period": f"{start_date} to {end_date}",
                    "summary": {
                        "events_count": len(events),
                        "signals_count": len(signals),
                        "actionables": actionables
                    }
                }]

            prompt = template.replace("{period_start}", start_date)\
                             .replace("{period_end}", end_date)\
                             .replace("{daily_summaries_json}", json.dumps(dailies_data, indent=2))

            response_str = query_gemini_api(prompt, api_key=self.api_key)
            if response_str.startswith("```"):
                lines = response_str.splitlines()
                if lines[0].startswith("```json") or lines[0].startswith("```"):
                    response_str = "\n".join(lines[1:-1])

            content = json.loads(response_str)

            markdown_brief = f"### Weekly Scorecard — {start_date} to {end_date}\n\n"
            markdown_brief += f"**Brief:** {content.get('ai_executive_summary', '')}\n\n"
            markdown_brief += "**Weekly Highlights:**\n" + content.get("key_highlights", "")

            summary = {
                "summary_id": f"sum_weekly_{start_date}_{end_date}",
                "summary_type": "weekly",
                "period_start": start_date,
                "period_end": end_date,
                "title": f"Weekly Scorecard — {start_date} to {end_date}",
                "content_json": json.dumps(content),
                "content_markdown": markdown_brief,
                "stats_json": json.dumps({
                    "days_covered": len(dailies)
                }),
                "pipeline_run_id": pipeline_run_id
            }

            add_summary(summary)
            logging.info(f"[SummaryEngine] Successfully generated weekly summary for {start_date}_{end_date}")
            return summary

        except Exception as e:
            logging.error(f"[SummaryEngine] Failed to generate weekly summary: {e}")
            return None

    # ─── Monthly Summary Generation ────────────────────────────
    
    def generate_monthly_summary(self, start_date: str, end_date: str, pipeline_run_id: str | None = None) -> dict | None:
        """
        Generate and save a monthly scorecard aggregating weekly summaries and period metrics.
        """
        logging.info(f"[SummaryEngine] Compiling monthly brief from {start_date} to {end_date}")
        
        # Load weekly summaries in range
        weeklies = []
        with get_db() as conn:
            rows = conn.execute(
                """SELECT * FROM summaries
                   WHERE summary_type = 'weekly' AND period_start >= ? AND period_end <= ?
                   ORDER BY period_start ASC""",
                (start_date, end_date)
            ).fetchall()
            weeklies = [dict(r) for r in rows]

        events, signals, actionables, open_actionables, dragging_issues = self._query_period_metrics(start_date, end_date)
        cluster_health = self._calc_dynamic_health(open_actionables, dragging_issues)

        has_active_weeklies = any(
            not json.loads(w.get("content_json", "{}")).get("not_enough_data", False)
            for w in weeklies if w.get("content_json")
        )

        if not has_active_weeklies and not events and not signals and not actionables:
            brief_text = f"Not enough data to generate summary for {start_date} to {end_date}"
            highlights_text = f"• Not enough data to generate summary for {start_date} to {end_date}"

            summary = {
                "summary_id": f"sum_monthly_{start_date}_{end_date}",
                "summary_type": "monthly",
                "period_start": start_date,
                "period_end": end_date,
                "title": f"Monthly Summary Scorecard — {start_date} to {end_date}",
                "content_json": json.dumps({
                    "top_issues": [],
                    "new_actionables": 0,
                    "resolved_actionables": 0,
                    "cluster_health": cluster_health,
                    "key_highlights": highlights_text,
                    "ai_executive_summary": brief_text,
                    "not_enough_data": True
                }),
                "content_markdown": f"### Monthly Scorecard — {start_date} to {end_date}\n\n**Brief:** {brief_text}\n\n**Monthly Highlights:**\n{highlights_text}",
                "stats_json": json.dumps({"weeks_covered": 0}),
                "pipeline_run_id": pipeline_run_id
            }
            add_summary(summary)
            return summary

        weeklies_data = []
        for w in weeklies:
            try:
                weeklies_data.append({
                    "period": f"{w['period_start']} to {w['period_end']}",
                    "summary": json.loads(w["content_json"])
                })
            except Exception:
                pass

        if not self.api_key:
            brief_text = f"Monthly scorecard for period {start_date} to {end_date} compiled from workspace communications."
            highlights_text = f"• Total Events: {len(events)}\n• Total Signals: {len(signals)}\n• Actionables Created: {len(actionables)}"
            summary = {
                "summary_id": f"sum_monthly_{start_date}_{end_date}",
                "summary_type": "monthly",
                "period_start": start_date,
                "period_end": end_date,
                "title": f"Monthly Summary Scorecard — {start_date} to {end_date}",
                "content_json": json.dumps({
                    "top_issues": [],
                    "new_actionables": len(actionables),
                    "resolved_actionables": sum(1 for a in actionables if a.get("status") in ("resolved", "dismissed")),
                    "cluster_health": cluster_health,
                    "key_highlights": highlights_text,
                    "ai_executive_summary": brief_text
                }),
                "content_markdown": f"### Monthly Scorecard — {start_date} to {end_date}\n\n**Brief:** {brief_text}\n\n**Monthly Highlights:**\n{highlights_text}",
                "stats_json": json.dumps({"weeks_covered": len(weeklies)}),
                "pipeline_run_id": pipeline_run_id
            }
            add_summary(summary)
            return summary

        try:
            try:
                template = load_prompt_template("monthly_summary_prompt.txt")
            except Exception:
                path = Path(__file__).resolve().parent / "prompts" / "monthly_summary_prompt.txt"
                template = path.read_text(encoding="utf-8")

            if not weeklies_data:
                weeklies_data = [{
                    "period": f"{start_date} to {end_date}",
                    "summary": {
                        "events_count": len(events),
                        "signals_count": len(signals),
                        "actionables": actionables
                    }
                }]

            prompt = template.replace("{period_start}", start_date)\
                             .replace("{period_end}", end_date)\
                             .replace("{weekly_summaries_json}", json.dumps(weeklies_data, indent=2))

            response_str = query_gemini_api(prompt, api_key=self.api_key)
            if response_str.startswith("```"):
                lines = response_str.splitlines()
                if lines[0].startswith("```json") or lines[0].startswith("```"):
                    response_str = "\n".join(lines[1:-1])

            content = json.loads(response_str)

            markdown_brief = f"### Monthly scorecard — {start_date} to {end_date}\n\n"
            markdown_brief += f"**Brief:** {content.get('ai_executive_summary', '')}\n\n"
            markdown_brief += "**Monthly Highlights:**\n" + content.get("key_highlights", "")

            summary = {
                "summary_id": f"sum_monthly_{start_date}_{end_date}",
                "summary_type": "monthly",
                "period_start": start_date,
                "period_end": end_date,
                "title": f"Monthly Summary Scorecard — {start_date} to {end_date}",
                "content_json": json.dumps(content),
                "content_markdown": markdown_brief,
                "stats_json": json.dumps({
                    "weeks_covered": len(weeklies)
                }),
                "pipeline_run_id": pipeline_run_id
            }

            add_summary(summary)
            logging.info(f"[SummaryEngine] Successfully generated monthly summary for {start_date}_{end_date}")
            return summary

        except Exception as e:
            logging.error(f"[SummaryEngine] Failed to generate monthly summary: {e}")
            return None

    # ─── Batch Update Active & Current Summaries ────────────────
    
    def update_all_active_summaries(self, target_date_str: str | None = None) -> None:
        """
        Calculates and updates daily, weekly, and monthly summaries for all active historical dates
        and the current week/month.
        """
        today_str = target_date_str or datetime.now().strftime("%Y-%m-%d")
        
        # 1. Collect all distinct thread dates from DB
        active_dates = set()
        with get_db() as conn:
            rows = conn.execute("SELECT DISTINCT thread_date FROM threads WHERE thread_date IS NOT NULL AND thread_date != ''").fetchall()
            for r in rows:
                active_dates.add(r["thread_date"])
        
        active_dates.add(today_str)
        sorted_dates = sorted(list(active_dates))

        weeks_to_process = set()
        months_to_process = set()

        for d in sorted_dates:
            # Generate daily summary
            self.generate_daily_summary(d)
            
            # Record week and month ranges
            w_start, w_end = get_week_range(d)
            m_start, m_end = get_month_range(d)
            weeks_to_process.add((w_start, w_end))
            months_to_process.add((m_start, m_end))

        # Always include current week and month
        curr_w_start, curr_w_end = get_week_range(today_str)
        curr_m_start, curr_m_end = get_month_range(today_str)
        weeks_to_process.add((curr_w_start, curr_w_end))
        months_to_process.add((curr_m_start, curr_m_end))

        # Generate/update weekly summaries
        for w_start, w_end in sorted(list(weeks_to_process)):
            self.generate_weekly_summary(w_start, w_end)

        # Generate/update monthly summaries
        for m_start, m_end in sorted(list(months_to_process)):
            self.generate_monthly_summary(m_start, m_end)
