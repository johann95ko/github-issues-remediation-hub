"""Aggregations behind the dashboard.

Every number answers a specific leadership question, so each function is named
after the question rather than the metric. All figures derive from the
remediations table — nothing here writes state.
"""

from __future__ import annotations

import time

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.remediation import Remediation

DONE_STATES = ("awaiting_review", "merged")
FAILED_STATES = ("failed", "escalated")
WEEK_SECONDS = 7 * 24 * 3600


# Conservative per-session spend assumed while the Devin API still reports
# 0 ACUs (consumption lands late in a session's life). Keeps the cost side of
# the ROI populated instead of showing $0 for work that clearly ran.
ESTIMATED_ACUS_PER_SESSION = 5.0


def cost_vs_benefit(db: Session) -> dict:
    """Q: does the benefit outweigh the cost, at a glance?"""
    settings = get_settings()
    reported_acus, unreported_sessions, hours_saved = db.execute(
        select(
            func.coalesce(func.sum(Remediation.acus_consumed), 0.0),
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Remediation.session_id != "")
                            & (Remediation.acus_consumed == 0),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            # Benefit is claimed only for remediations that produced a
            # reviewable PR; failures and escalations earn zero, which keeps
            # the ROI story honest.
            func.coalesce(
                func.sum(
                    case(
                        (Remediation.state.in_(DONE_STATES), Remediation.baseline_hours),
                        else_=0.0,
                    )
                ),
                0.0,
            ),
        )
    ).one()
    estimated_acus = unreported_sessions * ESTIMATED_ACUS_PER_SESSION
    total_acus = reported_acus + estimated_acus
    cost_usd = total_acus * settings.usd_per_acu
    benefit_usd = hours_saved * settings.engineer_usd_per_hour
    return {
        "total_acus": round(total_acus, 2),
        "cost_is_estimated": estimated_acus > 0,
        "cost_usd": round(cost_usd, 2),
        "engineer_hours_saved": round(hours_saved, 1),
        "benefit_usd": round(benefit_usd, 2),
        "roi_multiple": round(benefit_usd / cost_usd, 2) if cost_usd > 0 else None,
        "assumptions": {
            "usd_per_acu": settings.usd_per_acu,
            "engineer_usd_per_hour": settings.engineer_usd_per_hour,
            "estimated_acus_per_unreported_session": ESTIMATED_ACUS_PER_SESSION,
        },
    }


def weekly_impact(db: Session) -> dict:
    """Q: what did this resolve in the last 7 days and what did it mean?"""
    cutoff = int(time.time()) - WEEK_SECONDS
    resolved = db.scalar(
        select(func.count())
        .select_from(Remediation)
        .where(Remediation.completed_at >= cutoff, Remediation.state.in_(DONE_STATES))
    )
    highlights = [
        {
            "repo": r.repo_full_name,
            "issue_number": r.issue_number,
            "title": r.issue_title,
            "pr_url": r.pr_url,
            "fix_summary": r.fix_summary,
            "root_cause": r.root_cause,
        }
        for r in db.scalars(
            select(Remediation)
            .where(Remediation.completed_at >= cutoff, Remediation.state.in_(DONE_STATES))
            .order_by(Remediation.completed_at.desc())
            .limit(5)
        )
    ]
    return {"resolved_last_7_days": resolved or 0, "highlights": highlights}


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
    review_queue = [
        {
            "repo": r.repo_full_name,
            "issue_number": r.issue_number,
            "title": r.issue_title,
            "pr_url": r.pr_url,
            "waiting_hours": round((now - (r.completed_at or now)) / 3600, 1),
        }
        for r in db.scalars(
            select(Remediation)
            .where(Remediation.state == "awaiting_review")
            .order_by(Remediation.completed_at.asc())
        )
    ]
    escalations = [
        {
            "repo": r.repo_full_name,
            "issue_number": r.issue_number,
            "title": r.issue_title,
            "session_url": r.session_url,
            "outcome": r.outcome or "needs_human",
        }
        for r in db.scalars(select(Remediation).where(Remediation.state == "escalated"))
    ]
    return {"review_queue": review_queue, "escalations": escalations}


def throughput(db: Session) -> dict:
    """Q: is the system keeping up? Success/failure split and daily volume."""
    total, succeeded, failed = db.execute(
        select(
            func.count(),
            func.coalesce(
                func.sum(case((Remediation.state.in_(DONE_STATES), 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((Remediation.state.in_(FAILED_STATES), 1), else_=0)), 0
            ),
        ).select_from(Remediation)
    ).one()
    day_expr = func.strftime(
        "%Y-%m-%d", func.datetime(Remediation.created_at, "unixepoch")
    )
    daily = [
        {"date": day, "started": started, "succeeded": ok, "failed": bad}
        for day, started, ok, bad in db.execute(
            select(
                day_expr,
                func.count(),
                func.coalesce(
                    func.sum(case((Remediation.state.in_(DONE_STATES), 1), else_=0)), 0
                ),
                func.coalesce(
                    func.sum(case((Remediation.state.in_(FAILED_STATES), 1), else_=0)), 0
                ),
            )
            .select_from(Remediation)
            .group_by(day_expr)
            .order_by(day_expr)
        )
    ]
    durations = sorted(
        db.scalars(
            select(Remediation.completed_at - Remediation.created_at).where(
                Remediation.completed_at != 0, Remediation.state.in_(DONE_STATES)
            )
        )
    )
    return {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "in_flight": total - succeeded - failed,
        "success_rate": round(succeeded / (succeeded + failed), 3) if (succeeded + failed) else None,
        "median_minutes_to_pr": round(durations[len(durations) // 2] / 60, 1) if durations else None,
        "daily": daily,
    }
