"""
Dashboard Pipeline — Core Orchestrator.

Implements the full Events → Signals → Clusters pipeline adapted from the
learning project's pipeline.py. Instead of stock news articles, this
processes Teams messages and Outlook emails.

Pipeline stages:
1. Thread Processing — Load and normalize ingested data
2. Event Extraction — LLM extracts organizational events from threads
3. Signal Clustering — LLM maps events to cluster signals with strength
4. Cluster Health Evaluation — LLM evaluates organizational health per cluster
5. Dragging Issue Detection — Identifies slow-burning unresolved problems
"""

import hashlib
import gc
import time
import os
import uuid
import requests
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

from dashboard.db import add_audit_log
from dashboard.registry import match_and_register_signal_type, match_and_register_cluster
from dashboard.decay import calculate_time_decay, detect_dragging_issues

from shared.gemini_client import query_gemini_api, load_prompt_template, clean_json_text
from shared.model_router import router, QuotaExhaustedError, PipelinePausedError

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# SAVEPOINT HELPERS
# ─────────────────────────────────────────────────────────────────────

def _create_savepoint(
    run_id: str,
    stage: str,
    batch_index: int,
    exhausted_model: str,
    partial_events: list,
    partial_signals: list,
    partial_actionables: list,
    cluster_registry: dict,
    signal_registry: dict
) -> str:
    """Persists a pipeline savepoint to SQLite and returns the savepoint_id."""
    from dashboard.db import save_savepoint
    savepoint_id = f"sp_{str(uuid.uuid4())[:8]}"
    save_savepoint({
        "savepoint_id": savepoint_id,
        "run_id": run_id,
        "stage": stage,
        "batch_index": batch_index,
        "exhausted_model": exhausted_model,
        "partial_events_json": json.dumps(partial_events),
        "partial_signals_json": json.dumps(partial_signals),
        "partial_actionables_json": json.dumps(partial_actionables),
        "cluster_registry_json": json.dumps(cluster_registry),
        "signal_registry_json": json.dumps(signal_registry),
        "created_at": datetime.now().isoformat(),
        "status": "paused"
    })
    logger.info(f"[Pipeline] Savepoint '{savepoint_id}' created at stage='{stage}', batch={batch_index}.")
    return savepoint_id


def resume_pipeline_from_savepoint(savepoint_id: str, api_key: str | None = None) -> dict:
    """
    Resumes a paused pipeline from a persisted savepoint.
    Re-runs only the remaining unprocessed batches from the saved batch_index onward.
    """
    from dashboard.db import (
        get_latest_savepoint, mark_savepoint_resumed, save_savepoint,
        add_event, add_signal, add_actionable, add_dragging_issue, add_pipeline_run, get_threads
    )

    if not api_key:
        api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        from shared.database import get_config
        api_key = get_config("gemini_api_key")

    # Load the specific savepoint by ID
    from shared.database import get_db
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM pipeline_savepoints WHERE savepoint_id = ?", (savepoint_id,)
        ).fetchone()

    if not row:
        raise ValueError(f"Savepoint '{savepoint_id}' not found.")

    sp = dict(row)
    stage = sp["stage"]
    batch_index = sp["batch_index"]
    partial_events = json.loads(sp["partial_events_json"] or "[]")
    partial_signals = json.loads(sp["partial_signals_json"] or "[]")
    partial_actionables = json.loads(sp["partial_actionables_json"] or "[]")
    cluster_registry = json.loads(sp["cluster_registry_json"] or "{}")
    signal_registry = json.loads(sp["signal_registry_json"] or "{}")
    run_id = sp["run_id"] or f"run_{str(uuid.uuid4())[:8]}_resume"

    logger.info(f"\n[Pipeline] Resuming from savepoint '{savepoint_id}' at stage='{stage}', batch={batch_index}")

    all_threads = [dict(t) for t in get_threads(limit_days=30)]

    # Resume event extraction from the saved batch_index
    if stage == "event_extraction":
        remaining_threads = all_threads[batch_index * 5:]  # default batch_size=5
        new_events, new_actionables = run_event_extraction(
            threads=remaining_threads,
            api_key=api_key,
            signal_registry=signal_registry
        )
        partial_events.extend(new_events)
        partial_actionables.extend(new_actionables)

    # Run (or resume) signal clustering
    if stage in ("event_extraction", "signal_clustering"):
        remaining_events = partial_events[batch_index * 30:] if stage == "signal_clustering" else partial_events
        new_signals, cluster_registry = run_signal_clustering(
            events=remaining_events if stage == "signal_clustering" else partial_events,
            api_key=api_key,
            cluster_registry=cluster_registry
        )
        partial_signals.extend(new_signals)

    # Cluster health evaluation
    dashboard_clusters = run_cluster_health_evaluation(
        signals=partial_signals,
        api_key=api_key,
        cluster_registry=cluster_registry
    )

    # Persist results
    for ev in partial_events:
        add_event(ev)
    for sig in partial_signals:
        add_signal(sig)
    for act in partial_actionables:
        add_actionable(act)

    dragging_issues = detect_dragging_issues(partial_signals)
    for drag in dragging_issues:
        drag_record = {
            "issue_id": f"drag_{str(uuid.uuid4())[:8]}",
            "thread_id": drag.get("thread_id", ""),
            "signal_id": drag.get("signal_id", ""),
            "title": f"{drag.get('signal_type', 'Unknown').replace('_', ' ').title()} — Unresolved",
            "description": drag.get("summary", ""),
            "days_unresolved": drag.get("days_unresolved", 0),
            "severity": drag.get("severity", "medium"),
            "first_detected_at": drag.get("timestamp", ""),
            "last_checked_at": datetime.now().isoformat(),
            "status": "active"
        }
        add_dragging_issue(drag_record)

    mark_savepoint_resumed(savepoint_id)

    add_pipeline_run({
        "run_id": run_id,
        "run_type": "resume",
        "status": "completed",
        "started_at": datetime.now().isoformat(),
        "completed_at": datetime.now().isoformat(),
        "stats_json": json.dumps({
            "events": len(partial_events),
            "signals": len(partial_signals),
            "actionables": len(partial_actionables)
        })
    })

    return {
        "paused": False,
        "threads": all_threads,
        "events": partial_events,
        "signals": partial_signals,
        "actionables": partial_actionables,
        "clusters": dashboard_clusters,
        "dragging_issues": dragging_issues,
        "stats": {
            "threads": len(all_threads),
            "events": len(partial_events),
            "signals": len(partial_signals),
            "actionables": len(partial_actionables),
            "dragging_issues": len(dragging_issues)
        }
    }


# ─────────────────────────────────────────────────────────────────────
# STAGE 2: EVENT EXTRACTION (LLM)
# ─────────────────────────────────────────────────────────────────────

def run_event_extraction(threads, api_key, signal_registry, batch_size=15, progress_callback=None):
    """
    Batches threads and sends them to Gemini to extract organizational events.
    Uses the self-healing signal type registry.
    """
    if not threads:
        logger.info("[Pipeline] No threads to process for event extraction.")
        return [], []

    logger.info(f"\n[Pipeline] Starting event extraction for {len(threads)} threads...")
    template = load_prompt_template("event_extraction_prompt.txt")

    extracted_events = []
    all_actionables = []

    # Build registry list for prompt
    registry_list = [
        {"signal_type": st, "category": info.get("category", "general"), "description": info.get("description", "")}
        for st, info in signal_registry.items()
    ]

    total_batches = (len(threads) + batch_size - 1) // batch_size

    for i in range(0, len(threads), batch_size):
        batch = threads[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        pct = round((batch_num / total_batches) * 100, 1)
        logger.info(f"\n[Pipeline] Processing Event Extraction Batch [{i+1}-{min(i+batch_size, len(threads))}] ({batch_num}/{total_batches})...")

        if progress_callback:
            try:
                progress_callback("pipeline_progress", {
                    "batch": batch_num,
                    "total_batches": total_batches,
                    "percent": pct,
                    "message": f"Extracting AI risk signals & actionables (Batch {batch_num}/{total_batches})..."
                })
            except Exception:
                pass

        # Format threads for prompt (cap text at 6000 chars per thread)
        formatted_threads = []
        for t in batch:
            formatted_threads.append({
                "thread_id": t["thread_id"],
                "source": t["source"],
                "subject": t["subject"],
                "participants": t["participants"],
                "message_count": t["message_count"],
                "first_message_at": t["first_message_at"],
                "last_message_at": t["last_message_at"],
                "team_name": t.get("team_name", ""),
                "channel_name": t.get("channel_name", ""),
                "text": t["raw_text"][:6000]
            })

        prompt = template.format(
            registry_json=json.dumps(registry_list, indent=2),
            threads_json=json.dumps(formatted_threads, indent=2)
        )

        # Per-batch: calculate token estimate for this batch and pick model
        batch_token_estimate = sum(t.get("estimated_tokens", len(t.get("raw_text", "")) // 4) for t in batch)
        try:
            selected_model = router.select_model(
                task_type="event_extraction",
                estimated_tokens=batch_token_estimate,
                run_id="",
                batch_index=i // batch_size
            )
        except QuotaExhaustedError:
            raise  # Let the orchestrator catch this and create a savepoint

        extracted_data = None
        for batch_attempt in range(1, 4):
            try:
                raw_json_str = query_gemini_api(
                    prompt,
                    model_name=selected_model,
                    api_key=api_key,
                    task_type="event_extraction",
                    estimated_tokens=batch_token_estimate
                )
                extracted_data = json.loads(clean_json_text(raw_json_str))
                break
            except QuotaExhaustedError:
                raise  # Propagate to orchestrator
            except Exception as e:
                logger.warning(f"    [Pipeline Batch Retry] Event extraction batch [{i+1}] attempt {batch_attempt}/3 failed: {e}")
                if batch_attempt < 3:
                    time.sleep(4 * batch_attempt)
                else:
                    logger.error(f"    [Pipeline Error] Event extraction failed for batch [{i+1}] after 3 attempts.")

        if not extracted_data:
            continue

        events = extracted_data.get("events", [])
        unknown_events = extracted_data.get("unknown_events", [])
        actionables = extracted_data.get("actionables", [])

        logger.info(f"    [Pipeline] Gemini returned {len(events)} known, {len(unknown_events)} unknown events, {len(actionables)} actionables.")

        # Process known events
        for idx, ev in enumerate(events, 1):
            t_id = ev.get("thread_id", "")
            signal_type = ev.get("signal_type", "").strip().lower()

            # Verify/match signal type
            signal_type = match_and_register_signal_type(signal_registry, signal_type, ev.get("summary", ""), ev.get("impact_area", "general"))

            event_id = f"ev_{t_id}_{idx}_{str(uuid.uuid4())[:4]}"

            # Find the thread's timestamp
            thread_ts = next((t["last_message_at"] for t in batch if t["thread_id"] == t_id), datetime.now().isoformat())

            event_record = {
                "event_id": event_id,
                "thread_id": t_id,
                "signal_type": signal_type,
                "impact_area": ev.get("impact_area", "general"),
                "direction": ev.get("direction", "neutral"),
                "confidence": float(ev.get("confidence", 0.8)),
                "summary": ev.get("summary", ""),
                "timestamp": thread_ts
            }
            extracted_events.append(event_record)
            logger.info(f"    [Event] Type: {signal_type} | Thread: {t_id} | {ev.get('summary', '')[:60]}")

            # Audit Logbook Entry
            add_audit_log(
                log_date=thread_ts[:10] if len(thread_ts) >= 10 else datetime.now().strftime("%Y-%m-%d"),
                stage="event_extraction",
                event_type="EVENTS_EXTRACTED",
                entity_id=event_id,
                details={
                    "thread_id": t_id,
                    "signal_type": signal_type,
                    "summary": ev.get("summary", "")[:100],
                    "impact_area": ev.get("impact_area", "general")
                }
            )

        # Process unknown events (self-healing registry)
        for idx, uev in enumerate(unknown_events, len(events) + 1):
            t_id = uev.get("thread_id", "")
            proposed_name = uev.get("new_signal_name", "")
            desc = uev.get("description", "")
            cat = uev.get("suggested_category", "general")

            resolved_type = match_and_register_signal_type(
                registry=signal_registry,
                proposed_type=proposed_name,
                description=desc,
                category=cat
            )

            event_id = f"ev_{t_id}_{idx}_{str(uuid.uuid4())[:4]}"
            thread_ts = next((t["last_message_at"] for t in batch if t["thread_id"] == t_id), datetime.now().isoformat())

            event_record = {
                "event_id": event_id,
                "thread_id": t_id,
                "signal_type": resolved_type,
                "impact_area": cat,
                "direction": "neutral",
                "confidence": float(uev.get("confidence", 0.7)),
                "summary": desc,
                "timestamp": thread_ts
            }
            extracted_events.append(event_record)
            logger.info(f"    [Event (New)] Type: {resolved_type} | Thread: {t_id}")

        # Process actionables
        for act in actionables:
            actionable_id = f"act_{str(uuid.uuid4())[:8]}"
            actionable_record = {
                "actionable_id": actionable_id,
                "thread_id": act.get("thread_id", ""),
                "event_id": "",
                "title": act.get("title", ""),
                "description": act.get("description", ""),
                "priority": act.get("priority", "medium"),
                "status": "open",
                "source": next((t["source"] for t in batch if t["thread_id"] == act.get("thread_id")), "unknown"),
                "created_at": datetime.now().isoformat(),
                "due_date": ""
            }
            all_actionables.append(actionable_record)

            # Audit Logbook Entry
            add_audit_log(
                log_date=datetime.now().strftime("%Y-%m-%d"),
                stage="event_extraction",
                event_type="ACTIONABLE_CREATED",
                entity_id=actionable_id,
                details={
                    "thread_id": act.get("thread_id", ""),
                    "title": act.get("title", ""),
                    "priority": act.get("priority", "medium"),
                    "source": actionable_record["source"]
                }
            )

        # Memory cleanup
        del prompt
        del extracted_data
        gc.collect()

    return extracted_events, all_actionables


# ─────────────────────────────────────────────────────────────────────
# STAGE 3: SIGNAL CLUSTERING (LLM)
# ─────────────────────────────────────────────────────────────────────

def run_signal_clustering(events, api_key, cluster_registry, batch_size=30, progress_callback=None):
    """
    Groups events and runs signal clustering via Gemini.
    Applies time decay to generated signals.
    Supports dynamic cluster proposals.
    """
    if not events:
        logger.info("\n[Pipeline] No events found for signal clustering.")
        return [], cluster_registry

    logger.info(f"\n[Pipeline] Batching {len(events)} events for signal clustering...")
    template = load_prompt_template("signal_clustering_prompt.txt")
    generated_signals = []

    total_batches = (len(events) + batch_size - 1) // batch_size

    for i in range(0, len(events), batch_size):
        events_batch = events[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        pct = round(50.0 + (batch_num / total_batches) * 30.0, 1)
        logger.info(f"\n[Pipeline] Processing Signal Cluster Batch [{i+1}-{min(i+batch_size, len(events))}] ({batch_num}/{total_batches})...")

        if progress_callback:
            try:
                progress_callback("pipeline_progress", {
                    "batch": batch_num,
                    "total_batches": total_batches,
                    "percent": pct,
                    "message": f"Clustering AI Risk Signals (Batch {batch_num}/{total_batches})..."
                })
            except Exception:
                pass

        re_run_batch = True
        attempts = 0

        while re_run_batch and attempts < 3:
            attempts += 1
            re_run_batch = False

            prompt = template.format(
                clusters_json=json.dumps(cluster_registry, indent=2),
                events_json=json.dumps(events_batch, indent=2)
            )

            try:
                selected_model = router.select_model(
                    task_type="signal_clustering",
                    estimated_tokens=len(json.dumps(events_batch)) // 4,
                    run_id="",
                    batch_index=i // batch_size
                )
            except QuotaExhaustedError:
                raise

            try:
                raw_json_str = query_gemini_api(
                    prompt,
                    model_name=selected_model,
                    api_key=api_key,
                    task_type="signal_clustering"
                )
                res_data = json.loads(clean_json_text(raw_json_str))
                signals = res_data.get("signals", [])
            except QuotaExhaustedError:
                raise
            except Exception as e:
                logger.error(f"    [Error] Signal clustering failed on attempt {attempts}: {str(e)}")
                break

            # Check for new cluster proposals
            for sig in signals:
                cluster_type = sig.get("cluster_type", "").strip().lower()

                if cluster_type == "new_cluster_proposed":
                    proposed = sig.get("proposed_cluster", {})
                    new_cluster_name = proposed.get("cluster_name", "").strip().lower()
                    new_desc = proposed.get("description", "Dynamically proposed cluster").strip()
                    new_cat = proposed.get("category", "general").strip()

                    try:
                        new_persistence = float(proposed.get("persistence", 0.6))
                    except (ValueError, TypeError):
                        new_persistence = 0.6

                    try:
                        new_decay_rate = float(proposed.get("decay_rate", 0.02))
                    except (ValueError, TypeError):
                        new_decay_rate = 0.02

                    if not new_cluster_name:
                        new_cluster_name = f"proposed_cluster_{str(uuid.uuid4())[:6]}"

                    if new_cluster_name not in cluster_registry:
                        logger.info(f"    [Registry] Gemini proposed new cluster '{new_cluster_name}'. Registering...")
                        cluster_registry[new_cluster_name] = {
                            "description": new_desc,
                            "category": new_cat,
                            "persistence": new_persistence,
                            "decay_rate": new_decay_rate
                        }
                        try:
                            from dashboard.db import add_cluster
                            add_cluster(new_cluster_name, new_cat, new_desc, new_persistence, new_decay_rate)
                        except Exception as e:
                            logger.error(f"    [Registry Error] Failed to save new cluster to DB: {e}")
                        re_run_batch = True
                        break

            if re_run_batch:
                logger.info("    [Registry] Re-running batch with updated cluster registry...")
                continue

            # Process signals
            for sig in signals:
                event_id = sig.get("event_id", "")
                thread_id = sig.get("thread_id", "")
                signal_type = sig.get("signal_type", "")
                cluster_type = sig.get("cluster_type", "")
                strength = float(sig.get("strength", 0))
                relevance = float(sig.get("relevance_score", 0.5))
                confidence = float(sig.get("confidence", 0.8))
                timestamp = sig.get("timestamp", "")

                # Get decay params from cluster registry
                c_info = cluster_registry.get(cluster_type, {})
                c_persistence = c_info.get("persistence", None)
                c_decay_rate = c_info.get("decay_rate", None)

                # Apply time decay
                decayed_strength, persistence, decay_rate = calculate_time_decay(
                    strength=strength,
                    cluster_type=cluster_type,
                    timestamp_str=timestamp,
                    persistence=c_persistence,
                    decay_rate=c_decay_rate
                )

                signal_id = f"sig_{event_id}_{str(uuid.uuid4())[:8]}"

                generated_signals.append({
                    "signal_id": signal_id,
                    "event_id": event_id,
                    "thread_id": thread_id,
                    "signal_type": signal_type,
                    "cluster_type": cluster_type,
                    "strength": strength,
                    "decayed_strength": decayed_strength,
                    "persistence": persistence,
                    "decay_rate": decay_rate,
                    "relevance_score": relevance,
                    "confidence": confidence,
                    "timestamp": timestamp
                })
                logger.info(f"    [Signal] Event: {event_id} → Cluster: {cluster_type} | Strength: {strength} → Decayed: {decayed_strength}")

                # Audit Logbook Entry
                add_audit_log(
                    log_date=timestamp[:10] if len(timestamp) >= 10 else datetime.now().strftime("%Y-%m-%d"),
                    stage="signal_clustering",
                    event_type="SIGNALS_GENERATED",
                    entity_id=signal_id,
                    details={
                        "event_id": event_id,
                        "thread_id": thread_id,
                        "cluster_type": cluster_type,
                        "strength": strength,
                        "decayed_strength": decayed_strength
                    }
                )

            re_run_batch = False

    return generated_signals, cluster_registry


# ─────────────────────────────────────────────────────────────────────
# STAGE 4: CLUSTER HEALTH EVALUATION (LLM)
# ─────────────────────────────────────────────────────────────────────

def run_cluster_health_evaluation(signals, api_key, cluster_registry):
    """
    Uses Gemini to evaluate the health of each organizational cluster
    based on the generated signals.
    """
    logger.info(f"\n[Pipeline] Evaluating cluster health for {len(cluster_registry)} clusters...")

    template = load_prompt_template("cluster_health_prompt.txt")

    # Build sectors data
    sectors_data = []
    for c_type, info in cluster_registry.items():
        sectors_data.append({
            "cluster_type": c_type,
            "description": info.get("description", ""),
            "category": info.get("category", "")
        })

    # Build signals data for prompt
    signals_data = []
    for s in signals:
        signals_data.append({
            "id": s["signal_id"],
            "cluster_type": s["cluster_type"],
            "signal_type": s["signal_type"],
            "decayed_strength": s["decayed_strength"],
            "relevance": s["relevance_score"],
            "confidence": s["confidence"],
            "summary": s.get("event_summary", "N/A"),
            "date": s["timestamp"]
        })

    prompt = template.format(
        sectors_json=json.dumps(sectors_data, indent=2),
        signals_json=json.dumps(signals_data, indent=2)
    )

    try:
        res_str = query_gemini_api(
            prompt,
            api_key=api_key,
            task_type="cluster_health"
        )
        eval_data = json.loads(clean_json_text(res_str)).get("evaluations", {})
    except Exception as e:
        logger.error(f"[Pipeline Error] Cluster health evaluation failed: {str(e)}")
        eval_data = {}

    # Fetch active open actionables and dragging issues from DB to factor into cluster health
    open_actionables_by_cluster = {}
    try:
        from shared.database import get_db
        with get_db() as conn:
            rows = conn.execute(
                """SELECT a.priority, a.title, t.subject FROM actionables a
                   LEFT JOIN threads t ON a.thread_id = t.thread_id
                   WHERE a.status IN ('open', 'in_progress')"""
            ).fetchall()
            for r in rows:
                prio = (r["priority"] or "medium").lower()
                text = (str(r["title"]) + " " + str(r["subject"] or "")).lower()
                matched_c = "delivery_risk"
                for c_k in cluster_registry.keys():
                    if c_k.replace("_", " ") in text:
                        matched_c = c_k
                        break
                if matched_c not in open_actionables_by_cluster:
                    open_actionables_by_cluster[matched_c] = []
                open_actionables_by_cluster[matched_c].append(prio)

            d_rows = conn.execute(
                """SELECT severity FROM dragging_issues WHERE status IN ('active', 'open', 'in_progress')"""
            ).fetchall()
            if d_rows:
                if "delivery_risk" not in open_actionables_by_cluster:
                    open_actionables_by_cluster["delivery_risk"] = []
                for dr in d_rows:
                    open_actionables_by_cluster["delivery_risk"].append((dr["severity"] or "high").lower())
    except Exception as ie:
        logger.warning(f"[Pipeline] Open actionables health calculation notice: {ie}")

    # Group signals by cluster for the dashboard
    cluster_signals_map = {c_type: [] for c_type in cluster_registry.keys()}
    for s in signals:
        c_type = s["cluster_type"]
        if c_type not in cluster_signals_map:
            cluster_signals_map[c_type] = []
        cluster_signals_map[c_type].append(s)

    # Build dashboard structure
    dashboard_clusters = {}
    for c_type, cluster_info in cluster_registry.items():
        sigs = cluster_signals_map.get(c_type, [])

        health_score = 100 if not sigs else 50
        status = "Healthy" if not sigs else "Stable"
        confidence = 1.0
        summary = "No signals have been recorded for this cluster yet."

        total_neg_strength = sum(abs(float(s.get("decayed_strength", 0))) for s in sigs if float(s.get("decayed_strength", 0)) < 0)

        if c_type in eval_data:
            sec_eval = eval_data[c_type]
            health_score = int(sec_eval.get("health_score", 50))
            status = sec_eval.get("status", "Stable")
            confidence = float(sec_eval.get("confidence", 1.0))
            summary = sec_eval.get("summary", "")
        elif sigs:
            health_score = max(20, int(100 - (total_neg_strength * 35)))
            status = "Warning" if health_score < 60 else "Stable"
            confidence = 0.7
            summary = f"Detected {len(sigs)} operational signals in this cluster."

        # Deduct score for active open actionables and dragging issues in this cluster
        cluster_open_prios = open_actionables_by_cluster.get(c_type, [])
        prio_penalties = {"blocker": 25, "critical": 25, "high": 15, "medium": 10, "low": 5, "info": 5}
        total_prio_penalty = sum(prio_penalties.get(p, 10) for p in cluster_open_prios)

        if total_prio_penalty > 0 or total_neg_strength > 0:
            penalty_score = max(15, int(100 - (total_neg_strength * 35) - total_prio_penalty))
            health_score = min(health_score, penalty_score)

            has_critical = any(p in ("critical", "blocker") for p in cluster_open_prios)
            has_high = any(p == "high" for p in cluster_open_prios)

            if health_score < 40 or has_critical:
                status = "Critical"
            elif health_score < 65 or has_high:
                status = "Warning"
            elif health_score < 80:
                status = "Stable"
            else:
                status = "Healthy"

        dashboard_clusters[c_type] = {
            "name": c_type.replace("_", " ").title(),
            "description": cluster_info.get("description", ""),
            "category": cluster_info.get("category", ""),
            "health_score": health_score,
            "status": status,
            "confidence": confidence,
            "summary": summary,
            "signal_count": len(sigs),
            "signals": sigs
        }

    return dashboard_clusters


# ─────────────────────────────────────────────────────────────────────
# FULL PIPELINE ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────

def run_full_pipeline(api_key: str = None, run_type: str = "scheduled", progress_callback=None) -> dict:
    """
    Executes the complete Events → Signals → Clusters pipeline.
    Returns a dashboard-ready state dict.
    """
    from dashboard.db import (
        init_db, get_signal_types, get_clusters, INITIAL_SIGNAL_TYPES,
        INITIAL_CLUSTERS, add_thread, add_event, add_signal, add_actionable,
        add_dragging_issue, clear_pipeline_data, add_pipeline_run, get_threads
    )

    if not api_key:
        api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is required. Set it in .env or provide it at runtime.")

    logger.info("\n" + "=" * 60)
    logger.info("FOUNDER BUDDY DASHBOARD PIPELINE — START")
    logger.info("=" * 60)
    start_time = time.time()
    
    # Track run ID audit
    run_id = f"run_{str(uuid.uuid4())[:8]}"
    add_pipeline_run({
        "run_id": run_id,
        "run_type": run_type,
        "status": "running",
        "started_at": datetime.now().isoformat()
    })

    try:
        # Initialize database
        init_db()

        # Clear previous pipeline data
        clear_pipeline_data()

        # Load registries from DB
        db_signal_types = get_signal_types()
        db_clusters = get_clusters()

        signal_registry = {
            st["signal_type"]: {"category": st["category"], "description": st["description"]}
            for st in (db_signal_types if db_signal_types else INITIAL_SIGNAL_TYPES)
        }

        cluster_registry = {
            cl["cluster_type"]: {
                "category": cl["category"],
                "description": cl["description"],
                "persistence": cl.get("persistence", 0.6),
                "decay_rate": cl.get("decay_rate", 0.02)
            }
            for cl in (db_clusters if db_clusters else INITIAL_CLUSTERS)
        }

        # Stage 1: Build threads from raw logs to SQLite database
        from threads.builder import ThreadBuilder
        builder = ThreadBuilder()
        builder.build_pending_threads()

        # Load threads from DB (Focus on past 30 days)
        all_threads = [dict(t) for t in get_threads(limit_days=30)]

        if not all_threads:
            logger.warning("[Pipeline] No threads found to process. Pipeline aborted.")
            add_pipeline_run({
                "run_id": run_id,
                "run_type": run_type,
                "status": "completed",
                "started_at": datetime.now().isoformat(),
                "completed_at": datetime.now().isoformat(),
                "stats_json": json.dumps({"threads": 0, "events": 0, "signals": 0})
            })
            return {
                "threads": [],
                "events": [],
                "signals": [],
                "actionables": [],
                "clusters": {},
                "dragging_issues": [],
                "stats": {"threads": 0, "events": 0, "signals": 0}
            }

        # Stage 2: Extract events (with savepoint support)
        try:
            extracted_events, actionables = run_event_extraction(
                threads=all_threads,
                api_key=api_key,
                signal_registry=signal_registry,
                batch_size=60,
                progress_callback=progress_callback
            )
        except QuotaExhaustedError as qe:
            savepoint_id = _create_savepoint(
                run_id=run_id,
                stage="event_extraction",
                batch_index=qe.batch_index,
                exhausted_model=qe.model,
                partial_events=[], partial_signals=[], partial_actionables=[],
                cluster_registry=cluster_registry, signal_registry=signal_registry
            )
            add_pipeline_run({
                "run_id": run_id, "run_type": run_type, "status": "paused",
                "started_at": datetime.now().isoformat(),
                "completed_at": datetime.now().isoformat(),
                "error_message": str(qe)
            })
            raise PipelinePausedError(
                savepoint_id=savepoint_id,
                stage="event_extraction",
                message=router.format_quota_warning(qe.model)
            )

        # Stage 3: Cluster signals (with savepoint support)
        try:
            generated_signals, updated_clusters = run_signal_clustering(
                events=extracted_events,
                api_key=api_key,
                cluster_registry=cluster_registry,
                batch_size=60,
                progress_callback=progress_callback
            )
        except QuotaExhaustedError as qe:
            savepoint_id = _create_savepoint(
                run_id=run_id,
                stage="signal_clustering",
                batch_index=qe.batch_index,
                exhausted_model=qe.model,
                partial_events=extracted_events,
                partial_signals=[],
                partial_actionables=actionables,
                cluster_registry=cluster_registry,
                signal_registry=signal_registry
            )
            add_pipeline_run({
                "run_id": run_id, "run_type": run_type, "status": "paused",
                "started_at": datetime.now().isoformat(),
                "completed_at": datetime.now().isoformat(),
                "error_message": str(qe)
            })
            raise PipelinePausedError(
                savepoint_id=savepoint_id,
                stage="signal_clustering",
                message=router.format_quota_warning(qe.model)
            )

        # Enrich signals with event + thread trace details
        events_map = {e["event_id"]: e for e in extracted_events}
        threads_map = {t["thread_id"]: t for t in all_threads}

        for sig in generated_signals:
            ev = events_map.get(sig["event_id"], {})
            t = threads_map.get(sig["thread_id"], {})
            sig["subject"] = t.get("subject", "No Subject")
            sig["summary"] = ev.get("summary", "")
            sig["impact_area"] = ev.get("impact_area", "general")
            sig["direction"] = ev.get("direction", "neutral")

        if progress_callback:
            try:
                progress_callback("pipeline_progress", {
                    "percent": 85.0,
                    "message": "Evaluating cluster health & executive scorecards..."
                })
            except Exception:
                pass

        # Stage 4: Cluster Health Evaluation
        dashboard_clusters = run_cluster_health_evaluation(
            signals=generated_signals,
            api_key=api_key,
            cluster_registry=updated_clusters
        )

        if progress_callback:
            try:
                progress_callback("pipeline_progress", {
                    "percent": 95.0,
                    "message": "Building ChromaDB vector embeddings for AI Chatbot..."
                })
            except Exception:
                pass

        # Persist results to SQLite DB
        for ev in extracted_events:
            add_event(ev)

        for sig in generated_signals:
            add_signal(sig)

        # Direct AI-extracted dragging_issue signal registration
        for ev in extracted_events:
            if ev.get("signal_type") == "dragging_issue":
                drag_record = {
                    "issue_id": f"drag_{str(uuid.uuid4())[:8]}",
                    "thread_id": ev.get("thread_id", ""),
                    "signal_id": "",
                    "title": f"Dragging Issue — {ev.get('summary', 'Stalled task')[:45]}",
                    "description": ev.get("summary", ""),
                    "days_unresolved": 5,
                    "severity": "high",
                    "first_detected_at": ev.get("timestamp", datetime.now().isoformat()),
                    "last_checked_at": datetime.now().isoformat(),
                    "status": "active"
                }
                add_dragging_issue(drag_record)

        # Stage 5: Time-Decay Dragging Issue Detection
        dragging_issues = detect_dragging_issues(generated_signals)
        for drag in dragging_issues:
            drag_record = {
                "issue_id": f"drag_{str(uuid.uuid4())[:8]}",
                "thread_id": drag.get("thread_id", ""),
                "signal_id": drag.get("signal_id", ""),
                "title": f"{drag.get('signal_type', 'Unknown').replace('_', ' ').title()} — Unresolved",
                "description": drag.get("summary", ""),
                "days_unresolved": drag.get("days_unresolved", 0),
                "severity": drag.get("severity", "medium"),
                "first_detected_at": drag.get("timestamp", ""),
                "last_checked_at": datetime.now().isoformat(),
                "status": "active"
            }
            add_dragging_issue(drag_record)

            # Audit Logbook Entry
            add_audit_log(
                log_date=drag.get("timestamp", "")[:10] if len(drag.get("timestamp", "")) >= 10 else datetime.now().strftime("%Y-%m-%d"),
                stage="dragging_detection",
                event_type="DRAGGING_ISSUE_DETECTED",
                entity_id=drag_record["issue_id"],
                details={
                    "thread_id": drag.get("thread_id", ""),
                    "title": drag_record["title"],
                    "days_unresolved": drag_record["days_unresolved"],
                    "severity": drag_record["severity"]
                }
            )

        duration = time.time() - start_time
        logger.info("\n" + "=" * 60)
        logger.info("DASHBOARD PIPELINE COMPLETE")
        logger.info(f"Duration: {duration:.2f} seconds")
        logger.info(f"Threads Processed:  {len(all_threads)}")
        logger.info(f"Events Extracted:   {len(extracted_events)}")
        logger.info(f"Signals Generated:  {len(generated_signals)}")
        logger.info(f"Actionables Found:  {len(actionables)}")
        logger.info(f"Dragging Issues:    {len(dragging_issues)}")
        logger.info("=" * 60)

        # Trigger Daily Summary generation for each unique thread date processed
        try:
            active_dates = sorted(list({t["thread_date"] for t in all_threads if t.get("thread_date")}))
            logger.info(f"[Pipeline] Triggering summary compilation for active dates: {active_dates}")
            from dashboard.summaries import SummaryEngine
            engine = SummaryEngine(api_key=api_key)
            for date_str in active_dates:
                engine.generate_daily_summary(date_str, pipeline_run_id=run_id)
            engine.update_all_active_summaries()
        except Exception as se:
            logger.error(f"[Pipeline] Summary auto-trigger failed: {se}")

        # Update pipeline audit log status to completed
        stats_json = json.dumps({
            "threads": len(all_threads),
            "events": len(extracted_events),
            "signals": len(generated_signals),
            "actionables": len(actionables),
            "dragging_issues": len(dragging_issues),
            "duration_seconds": round(duration, 2)
        })
        add_pipeline_run({
            "run_id": run_id,
            "run_type": run_type,
            "status": "completed",
            "started_at": datetime.now().isoformat(),
            "completed_at": datetime.now().isoformat(),
            "stats_json": stats_json
        })

        # Remove raw_text from threads to save memory in response
        for t in all_threads:
            if "raw_text" in t:
                del t["raw_text"]

        # Trigger ThreadIndexer to chunk, embed, and store vectors into ChromaDB for Ask Buddy RAG
        try:
            from rag.indexer import ThreadIndexer
            logger.info("[Pipeline] Auto-indexing communication threads into ChromaDB vector store...")
            indexer = ThreadIndexer(api_key=api_key)
            indexed_count = indexer.index_pending_threads(clear_first=False)
            logger.info(f"[Pipeline] Vector indexing complete. Indexed {indexed_count} text chunks into ChromaDB.")
        except Exception as ie:
            logger.error(f"[Pipeline] Failed to index threads into vector store: {ie}")

        return {
            "threads": all_threads,
            "events": extracted_events,
            "signals": generated_signals,
            "actionables": actionables,
            "clusters": dashboard_clusters,
            "dragging_issues": dragging_issues,
            "stats": {
                "threads": len(all_threads),
                "events": len(extracted_events),
                "signals": len(generated_signals),
                "actionables": len(actionables),
                "dragging_issues": len(dragging_issues),
                "duration_seconds": round(duration, 2)
            }
        }

    except PipelinePausedError as ppe:
        logger.warning(f"[Pipeline] Run {run_id} paused at '{ppe.stage}'. Savepoint: {ppe.savepoint_id}")
        return {
            "paused": True,
            "savepoint_id": ppe.savepoint_id,
            "stage": ppe.stage,
            "message": ppe.message,
            "threads": [], "events": [], "signals": [],
            "actionables": [], "clusters": {}, "dragging_issues": [],
            "stats": {"threads": 0, "events": 0, "signals": 0}
        }
    except Exception as e:
        # Record failure status
        add_pipeline_run({
            "run_id": run_id,
            "run_type": run_type,
            "status": "failed",
            "error_message": str(e),
            "started_at": datetime.now().isoformat(),
            "completed_at": datetime.now().isoformat()
        })
        logger.error(f"[Pipeline] Run {run_id} failed: {e}", exc_info=True)
        raise e
