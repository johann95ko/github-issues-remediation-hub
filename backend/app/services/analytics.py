"""Aggregations behind the dashboard.

Every number answers a specific leadership question, so each function is named
after the question rather than the metric. All figures derive from the
remediations table — nothing here writes state.
"""

from __future__ import annotations

import time
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.remediation import Remediation

DONE_STATES = ("awaiting_review", "merged")
FAILED_STATES = ("failed", "escalated")
WEEK_SECONDS = 7 * 24 * 3600


def _all(db: Session) -> list[Remediation]:
    return list(db.scalars(select(Remediation)))


def cost_vs_benefit(db: Session) -> dict:
    """Q: does the benefit outweigh the cost, at a glance?"""
    settings = get_settings()
    rows = _all(db)
    total_acus = sum(r.acus_consumed for r in rows)
    cost_usd = total_acus * settings.usd_per_acu
    # Benefit is claimed only for remediations that produced a reviewable PR;
    # failures and escalations earn zero, which keeps the ROI story honest.
    hours_saved = sum(r.baseline_hours for r in rows if r.state in DONE_STATES)
    benefit_usd = hours_saved * settings.engineer_usd_per_hour
    return {
        "total_acus": round(total_acus, 2),
        "cost_usd": round(cost_usd, 2),
        "engineer_hours_saved": round(hours_saved, 1),
        "benefit_usd": round(benefit_usd, 2),
        "roi_multiple": round(benefit_usd / cost_usd, 2) if cost_usd > 0 else None,
        "assumptions": {
            "usd_per_acu": settings.usd_per_acu,
            "engineer_usd_per_hour": settings.engineer_usd_per_hour,
        },
    }


def weekly_impact(db: Session) -> dict:
    """Q: what did this resolve in the last 7 days and what did it mean?"""
    cutoff = int(time.time()) - WEEK_SECONDS
    rows = [r for r in _all(db) if r.completed_at >= cutoff and r.state in DONE_STATES]
    highlights = [
        {
            "repo": r.repo_full_name,
            "issue_number": r.issue_number,
            "title": r.issue_title,
            "pr_url": r.pr_url,
            "root_cause": r.root_cause,
        }
        for r in sorted(rows, key=lambda r: r.completed_at, reverse=True)[:5]
    ]
    return {"resolved_last_7_days": len(rows), "highlights": highlights}


def live_agents(db: Session) -> list[dict]:
    """Q: how many agents are running right now and what are they doing?"""
    rows = db.scalars(
        select(Remediation).where(Remediation.state.in_(("queued", "running")))
    )
    return [
        {
            "repo": r.repo_full_name,
            "issue_number": r.issue_number,
            "title": r.issue_title,
            "session_url": r.session_url,
            "status_detail": r.devin_status_detail or r.devin_status or r.state,
            "acus_so_far": r.acus_consumed,
            "running_seconds": int(time.time()) - r.created_at,
        }
        for r in rows
    ]


def attention_needed(db: Session) -> dict:
    """Q: where should I put people/resources right now?

    Ranked queue of items only a human can move: PRs waiting on review and
    escalated sessions. Age is the sort key because stale reviews are the
    usual bottleneck.
    """
    now = int(time.time())
    rows = _all(db)
    review_queue = sorted(
        (
            {
                "repo": r.repo_full_name,
                "issue_number": r.issue_number,
                "title": r.issue_title,
                "pr_url": r.pr_url,
                "waiting_hours": round((now - (r.completed_at or now)) / 3600, 1),
            }
            for r in rows
            if r.state == "awaiting_review"
        ),
        key=lambda item: -item["waiting_hours"],
    )
    escalations = [
        {
            "repo": r.repo_full_name,
            "issue_number": r.issue_number,
            "title": r.issue_title,
            "session_url": r.session_url,
            "outcome": r.outcome or "needs_human",
        }
        for r in rows
        if r.state == "escalated"
    ]
    return {"review_queue": review_queue, "escalations": escalations}


def throughput(db: Session) -> dict:
    """Q: is the system keeping up? Success/failure split and daily volume."""
    rows = _all(db)
    total = len(rows)
    succeeded = sum(1 for r in rows if r.state in DONE_STATES)
    failed = sum(1 for r in rows if r.state in FAILED_STATES)
    per_day: dict[str, dict[str, int]] = defaultdict(lambda: {"succeeded": 0, "failed": 0, "started": 0})
    for r in rows:
        day = time.strftime("%Y-%m-%d", time.gmtime(r.created_at))
        per_day[day]["started"] += 1
        if r.state in DONE_STATES:
            per_day[day]["succeeded"] += 1
        elif r.state in FAILED_STATES:
            per_day[day]["failed"] += 1
    durations = [
        r.completed_at - r.created_at for r in rows if r.completed_at and r.state in DONE_STATES
    ]
    return {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "in_flight": total - succeeded - failed,
        "success_rate": round(succeeded / (succeeded + failed), 3) if (succeeded + failed) else None,
        "median_minutes_to_pr": round(sorted(durations)[len(durations) // 2] / 60, 1) if durations else None,
        "daily": [{"date": day, **counts} for day, counts in sorted(per_day.items())],
    }
