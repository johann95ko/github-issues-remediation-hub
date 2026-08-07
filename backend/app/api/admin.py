"""Write API for the Engineering view: repository connections and
review of agent-discovered issues.
"""

from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.discovered_issue import DiscoveredIssue
from app.models.repo import MonitoredRepo
from app.models.repo_scan import RepoScan

router = APIRouter(prefix="/api")


class RepoIn(BaseModel):
    full_name: str = Field(min_length=3, pattern=r"^[\w.-]+/[\w.-]+$")
    trigger_labels: list[str] = ["devin-fix"]
    merge_policy: str = "review"
    max_acu_per_session: int = Field(default=15, ge=1, le=100)
    baseline_engineer_hours_per_issue: float = Field(default=4.0, ge=0)
    enabled: bool = True


def _repo_out(repo: MonitoredRepo) -> dict:
    return {
        "id": repo.id,
        "full_name": repo.full_name,
        "trigger_labels": repo.labels_list(),
        "merge_policy": repo.merge_policy,
        "max_acu_per_session": repo.max_acu_per_session,
        "baseline_engineer_hours_per_issue": repo.baseline_engineer_hours_per_issue,
        "enabled": repo.enabled,
    }


@router.get("/repos")
def list_repos(db: Session = Depends(get_db)):
    return [_repo_out(r) for r in db.scalars(select(MonitoredRepo).order_by(MonitoredRepo.id))]


@router.post("/repos", status_code=201)
def add_repo(body: RepoIn, db: Session = Depends(get_db)):
    if body.merge_policy not in ("review", "auto_merge"):
        raise HTTPException(422, "merge_policy must be 'review' or 'auto_merge'")
    exists = db.scalar(select(MonitoredRepo).where(MonitoredRepo.full_name == body.full_name))
    if exists:
        raise HTTPException(409, f"{body.full_name} is already connected")
    repo = MonitoredRepo(
        full_name=body.full_name,
        trigger_labels=",".join(body.trigger_labels),
        merge_policy=body.merge_policy,
        max_acu_per_session=body.max_acu_per_session,
        baseline_engineer_hours_per_issue=body.baseline_engineer_hours_per_issue,
        enabled=body.enabled,
    )
    db.add(repo)
    db.commit()
    return _repo_out(repo)


@router.patch("/repos/{repo_id}")
def update_repo(repo_id: int, body: RepoIn, db: Session = Depends(get_db)):
    repo = db.get(MonitoredRepo, repo_id)
    if repo is None:
        raise HTTPException(404, "repository not found")
    repo.full_name = body.full_name
    repo.trigger_labels = ",".join(body.trigger_labels)
    repo.merge_policy = body.merge_policy
    repo.max_acu_per_session = body.max_acu_per_session
    repo.baseline_engineer_hours_per_issue = body.baseline_engineer_hours_per_issue
    repo.enabled = body.enabled
    db.commit()
    return _repo_out(repo)


@router.delete("/repos/{repo_id}", status_code=204)
def delete_repo(repo_id: int, db: Session = Depends(get_db)):
    repo = db.get(MonitoredRepo, repo_id)
    if repo is None:
        raise HTTPException(404, "repository not found")
    db.delete(repo)
    db.commit()


@router.post("/repos/{repo_id}/scan", status_code=202)
async def scan_repo(repo_id: int, request: Request, db: Session = Depends(get_db)):
    repo = db.get(MonitoredRepo, repo_id)
    if repo is None:
        raise HTTPException(404, "repository not found")
    if not repo.enabled:
        raise HTTPException(409, f"{repo.full_name} is paused; re-enable it before scanning")
    scan = await request.app.state.orchestrator.start_scan(db, repo)
    if scan is None:
        raise HTTPException(409, f"a scan of {repo.full_name} is already in progress")
    return _scan_out(scan)


@router.get("/scans")
def list_scans(db: Session = Depends(get_db)):
    rows = db.scalars(select(RepoScan).order_by(RepoScan.created_at.desc()).limit(20))
    return [_scan_out(s) for s in rows]


def _scan_out(scan: RepoScan) -> dict:
    return {
        "id": scan.id,
        "repo": scan.repo_full_name,
        "state": scan.state,
        "session_id": scan.session_id,
        "session_url": scan.session_url,
        "summary": scan.summary,
        "findings_count": scan.findings_count,
        "acus_consumed": scan.acus_consumed,
        "created_at": scan.created_at,
        "completed_at": scan.completed_at,
    }


@router.get("/discovered-issues")
def list_discovered(db: Session = Depends(get_db)):
    rows = db.scalars(select(DiscoveredIssue).order_by(DiscoveredIssue.created_at.desc()))
    return [
        {
            "id": d.id,
            "repo": d.repo_full_name,
            "source_issue_number": d.source_issue_number,
            "title": d.title,
            "description": d.description,
            "severity": d.severity,
            "status": d.status,
            "filed_issue_url": d.filed_issue_url,
            "created_at": d.created_at,
            "scan_id": d.scan_id,
            # Prefilled GitHub "new issue" link: promotion needs one click and
            # zero GitHub credentials on the hub.
            "file_url": _new_issue_url(d),
        }
        for d in rows
    ]


@router.post("/discovered-issues/{issue_id}/{action}")
def review_discovered(issue_id: int, action: str, db: Session = Depends(get_db)):
    if action not in ("approve", "dismiss"):
        raise HTTPException(422, "action must be 'approve' or 'dismiss'")
    finding = db.get(DiscoveredIssue, issue_id)
    if finding is None:
        raise HTTPException(404, "finding not found")
    finding.status = "filed" if action == "approve" else "dismissed"
    db.commit()
    return {"id": finding.id, "status": finding.status, "file_url": _new_issue_url(finding)}


def _new_issue_url(finding: DiscoveredIssue) -> str:
    if finding.scan_id:
        provenance = "Discovered by Devin during a proactive repository scan."
    else:
        provenance = (
            f"Discovered by Devin while remediating "
            f"{finding.repo_full_name}#{finding.source_issue_number}."
        )
    body = f"{finding.description}\n\n---\n{provenance}"
    query = urllib.parse.urlencode({"title": finding.title, "body": body, "labels": "devin-discovered"})
    return f"https://github.com/{finding.repo_full_name}/issues/new?{query}"
