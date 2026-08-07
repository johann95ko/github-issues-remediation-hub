"""Read-only API consumed by the dashboard frontend."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.models.remediation import Remediation
from app.services import analytics

router = APIRouter(prefix="/api")


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    """Single round-trip powering the leadership view — leaders get one page,
    not a click path."""
    return {
        "cost_vs_benefit": analytics.cost_vs_benefit(db),
        "weekly_impact": analytics.weekly_impact(db),
        "live_agents": analytics.live_agents(db),
        "attention_needed": analytics.attention_needed(db),
        "throughput": analytics.throughput(db),
        "demo_mode": get_settings().demo_mode,
    }


@router.get("/remediations")
def remediations(
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
    before: int | None = Query(default=None, description="created_at cursor"),
):
    """Audit trail for the technical view, newest first. `before` pages
    backward through history so the payload stays bounded as it grows."""
    query = select(Remediation).order_by(Remediation.created_at.desc()).limit(limit)
    if before is not None:
        query = query.where(Remediation.created_at < before)
    rows = db.scalars(query)
    return [
        {
            "id": r.id,
            "repo": r.repo_full_name,
            "issue_number": r.issue_number,
            "issue_title": r.issue_title,
            "issue_url": r.issue_url,
            "labels": [x for x in r.issue_labels.split(",") if x],
            "session_id": r.session_id,
            "session_url": r.session_url,
            "state": r.state,
            "devin_status": r.devin_status,
            "devin_status_detail": r.devin_status_detail,
            "outcome": r.outcome,
            "problem_summary": r.problem_summary,
            "fix_summary": r.fix_summary,
            "root_cause": r.root_cause,
            "tests_run": r.tests_run,
            "confidence": r.confidence,
            "pr_url": r.pr_url,
            "pr_state": r.pr_state,
            "acus_consumed": r.acus_consumed,
            "merge_policy": r.merge_policy,
            "created_at": r.created_at,
            "completed_at": r.completed_at,
        }
        for r in rows
    ]


@router.get("/health")
def health():
    return {"status": "ok"}
