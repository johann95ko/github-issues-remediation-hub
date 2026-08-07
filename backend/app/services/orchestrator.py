"""Turns a qualified GitHub issue event into a managed Devin session.

Responsibilities kept here (and only here):
  * event filtering  - is this repo monitored, does the label qualify it
  * deduplication    - one live remediation per issue, even on redelivery
  * session creation - prompt, tags, budget, structured output contract
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.remediation import Remediation
from app.models.repo import MonitoredRepo
from app.models.repo_scan import RepoScan
from app.services.devin_client import (
    REMEDIATION_OUTPUT_SCHEMA,
    SCAN_OUTPUT_SCHEMA,
    DevinClientProtocol,
    build_remediation_prompt,
    build_scan_prompt,
)

logger = logging.getLogger(__name__)

# States where a new event for the same issue must NOT spawn another session.
ACTIVE_STATES = ("queued", "running")


class Orchestrator:
    def __init__(self, devin: DevinClientProtocol) -> None:
        self._devin = devin

    def should_remediate(
        self, db: Session, repo_full_name: str, labels: list[str]
    ) -> MonitoredRepo | None:
        repo = db.scalar(
            select(MonitoredRepo).where(MonitoredRepo.full_name == repo_full_name)
        )
        if repo is None or not repo.enabled:
            logger.info("Ignoring event for unmonitored/disabled repo %s", repo_full_name)
            return None
        if not set(label.lower() for label in labels) & set(
            trigger.lower() for trigger in repo.labels_list()
        ):
            logger.info(
                "Issue in %s lacks trigger labels %s", repo_full_name, repo.trigger_labels
            )
            return None
        return repo

    def accept_remediation(
        self,
        db: Session,
        repo: MonitoredRepo,
        issue_number: int,
        issue_title: str,
        issue_body: str,
        issue_url: str,
        labels: list[str],
    ) -> Remediation | None:
        """Persist a queued remediation (dedupe included) without calling the
        Devin API — the ingest queue launches it. Keeps the webhook response
        inside GitHub's delivery timeout regardless of API latency."""
        existing = db.scalar(
            select(Remediation).where(
                Remediation.repo_full_name == repo.full_name,
                Remediation.issue_number == issue_number,
                Remediation.state.in_(ACTIVE_STATES),
            )
        )
        if existing is not None:
            # GitHub redelivers webhooks; a duplicate here would double-spend.
            logger.info(
                "Issue #%s already has active remediation (session %s); skipping",
                issue_number,
                existing.session_id,
            )
            return None

        record = Remediation(
            repo_full_name=repo.full_name,
            issue_number=issue_number,
            issue_title=issue_title,
            issue_url=issue_url,
            issue_labels=",".join(labels),
            issue_body=issue_body,
            baseline_hours=repo.baseline_engineer_hours_per_issue,
            merge_policy=repo.merge_policy,
            max_acus=repo.max_acu_per_session,
            state="queued",
        )
        db.add(record)
        db.commit()
        return record

    async def launch_remediation(self, db: Session, record: Remediation) -> None:
        payload = {
            "prompt": build_remediation_prompt(
                record.repo_full_name,
                record.issue_number,
                record.issue_title,
                record.issue_body,
                record.issue_url,
            ),
            "title": f"Remediate {record.repo_full_name}#{record.issue_number}: {record.issue_title[:80]}",
            "tags": [
                "auto-remediation",
                f"issue-{record.issue_number}",
                record.repo_full_name.replace("/", "--"),
            ],
            "max_acu_limit": record.max_acus,
            "structured_output_required": True,
            "structured_output_schema": REMEDIATION_OUTPUT_SCHEMA,
            # Disposable sessions: the PR is the artifact; keeping VMs resumable
            # for fire-and-forget remediation only adds cost.
            "resumable": False,
        }

        try:
            session = await self._devin.create_session(payload)
        except Exception:
            logger.exception(
                "Failed to create Devin session for issue #%s", record.issue_number
            )
            record.state = "failed"
            record.outcome = "session_create_error"
            record.touch()
            db.commit()
            return

        record.session_id = session["session_id"]
        record.session_url = session.get("url", "")
        record.state = "running"
        record.devin_status = session.get("status", "running")
        record.touch()
        db.commit()
        logger.info(
            "Started session %s for issue #%s", record.session_id, record.issue_number
        )

    async def start_scan(self, db: Session, repo: MonitoredRepo) -> RepoScan | None:
        existing = db.scalar(
            select(RepoScan).where(
                RepoScan.repo_full_name == repo.full_name,
                RepoScan.state.in_(ACTIVE_STATES),
            )
        )
        if existing is not None:
            # One live scan per repo: a second concurrent scan of the same
            # code only duplicates findings and spend.
            return None

        scan = RepoScan(repo_full_name=repo.full_name, state="queued")
        db.add(scan)
        db.commit()

        payload = {
            "prompt": build_scan_prompt(repo.full_name),
            "title": f"Proactive defect scan: {repo.full_name}",
            "tags": ["repo-scan", repo.full_name.replace("/", "--")],
            "max_acu_limit": repo.max_acu_per_session,
            "structured_output_required": True,
            "structured_output_schema": SCAN_OUTPUT_SCHEMA,
            "resumable": False,
        }

        try:
            session = await self._devin.create_session(payload)
        except Exception:
            logger.exception("Failed to create scan session for %s", repo.full_name)
            scan.state = "failed"
            scan.touch()
            db.commit()
            return scan

        scan.session_id = session["session_id"]
        scan.session_url = session.get("url", "")
        scan.state = "running"
        scan.devin_status = session.get("status", "running")
        scan.touch()
        db.commit()
        logger.info("Started scan session %s for %s", scan.session_id, repo.full_name)
        return scan
