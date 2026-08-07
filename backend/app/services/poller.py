"""Background reconciliation loop.

Polling (vs. waiting on callbacks) is deliberate: the Devin API has no
outbound webhooks, and a reconciler that re-derives state from GET /sessions
is self-healing — a crashed hub picks up exactly where it left off after a
restart because the database, not memory, holds the state machine.
"""

from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.discovered_issue import DiscoveredIssue
from app.models.remediation import Remediation
from app.models.repo_scan import RepoScan
from app.services.devin_client import DevinClientProtocol

logger = logging.getLogger(__name__)

# Bounded fan-out: enough parallelism that a cycle over hundreds of active
# sessions finishes well inside the poll interval, without hammering the API.
MAX_CONCURRENT_POLLS = 10

# One automated nudge for a stuck session, then a human takes over. More than
# that and two automated systems end up talking to each other.
MAX_NUDGES = 1

NUDGE_MESSAGE = (
    "Automated check-in from the remediation hub: if you are blocked, please "
    "summarize what you need in the structured output (outcome='blocked') and "
    "finish the session so a human can take over."
)


class Poller:
    def __init__(self, devin: DevinClientProtocol) -> None:
        self._devin = devin
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        interval = get_settings().poll_interval_seconds
        while True:
            try:
                await self.reconcile_once()
            except Exception:
                logger.exception("Reconcile cycle failed; retrying next interval")
            await asyncio.sleep(interval)

    async def reconcile_once(self) -> None:
        # Only ids are read up front; each sync task opens its own session so
        # concurrent tasks never share an ORM Session (they aren't task-safe).
        with SessionLocal() as db:
            # Escalated rows whose underlying session is still live are
            # re-synced too, so a mis-escalation self-heals once the session
            # reports a PR/outcome.
            record_ids = db.scalars(
                select(Remediation.id).where(
                    Remediation.session_id != "",
                    (Remediation.state == "running")
                    | (
                        (Remediation.state == "escalated")
                        & (Remediation.devin_status == "running")
                    ),
                )
            ).all()
            scan_ids = db.scalars(
                select(RepoScan.id).where(
                    RepoScan.session_id != "",
                    RepoScan.state == "running",
                )
            ).all()

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_POLLS)

        async def sync_one(record_id: int, is_scan: bool) -> None:
            async with semaphore:
                with SessionLocal() as db:
                    if is_scan:
                        scan = db.get(RepoScan, record_id)
                        if scan is not None:
                            await self._sync_scan(db, scan)
                    else:
                        record = db.get(Remediation, record_id)
                        if record is not None:
                            await self._sync_record(db, record)

        await asyncio.gather(
            *(sync_one(rid, False) for rid in record_ids),
            *(sync_one(sid, True) for sid in scan_ids),
        )

    async def _sync_record(self, db, record: Remediation) -> None:
        try:
            session = await self._devin.get_session(record.session_id)
        except Exception:
            logger.exception("Failed to poll session %s", record.session_id)
            return

        record.devin_status = session.get("status", "")
        record.devin_status_detail = session.get("status_detail") or ""
        record.acus_consumed = float(session.get("acus_consumed") or 0.0)

        prs = session.get("pull_requests") or []
        if prs:
            record.pr_url = prs[0].get("pr_url", "")
            record.pr_state = prs[0].get("pr_state") or ""

        output = session.get("structured_output") or {}
        if output:
            record.outcome = output.get("outcome", record.outcome)
            record.problem_summary = output.get("problem_summary", record.problem_summary)
            record.fix_summary = output.get("fix_summary", record.fix_summary)
            record.root_cause = output.get("root_cause", record.root_cause)
            record.tests_run = output.get("tests_run", record.tests_run)
            record.confidence = output.get("confidence", record.confidence)
            if not record.pr_url and output.get("pr_url"):
                record.pr_url = output["pr_url"]
            self._capture_discovered_issues(db, record, output.get("discovered_issues") or [])

        status = record.devin_status
        detail = record.devin_status_detail

        if status == "exit":
            record.state = self._terminal_state(record)
            record.completed_at = int(time.time())
        elif status == "error":
            record.state = "failed"
            record.completed_at = int(time.time())
        elif status == "suspended" or (status == "running" and detail == "waiting_for_user"):
            # "waiting_for_user" with a PR and a reported outcome is Devin
            # done and awaiting review, not stuck — close it out as terminal.
            if record.pr_url and record.outcome:
                record.state = self._terminal_state(record)
                record.completed_at = int(time.time())
            elif record.nudge_count < MAX_NUDGES:
                record.nudge_count += 1
                try:
                    await self._devin.send_message(record.session_id, NUDGE_MESSAGE)
                except Exception:
                    logger.exception("Nudge failed for %s", record.session_id)
            else:
                # Escalation is a terminal state for automation — it lands on
                # the technical dashboard as "needs a human".
                record.state = "escalated"
                record.completed_at = int(time.time())

        record.touch()
        db.commit()

    async def _sync_scan(self, db, scan: RepoScan) -> None:
        try:
            session = await self._devin.get_session(scan.session_id)
        except Exception:
            logger.exception("Failed to poll scan session %s", scan.session_id)
            return

        scan.devin_status = session.get("status", "")
        scan.devin_status_detail = session.get("status_detail") or ""
        scan.acus_consumed = float(session.get("acus_consumed") or 0.0)

        output = session.get("structured_output") or {}
        if output:
            scan.summary = output.get("summary", scan.summary)
            scan.findings_count = self._capture_scan_findings(
                db, scan, output.get("discovered_issues") or []
            )

        status = scan.devin_status
        # A scan has no PR to wait on: any terminal or waiting status once the
        # structured output has arrived means the audit is done.
        if status == "error":
            scan.state = "failed"
            scan.completed_at = int(time.time())
        elif status == "exit" or (output and status in ("suspended", "running") and scan.devin_status_detail == "waiting_for_user"):
            scan.state = "completed"
            scan.completed_at = int(time.time())

        scan.touch()
        db.commit()

    @staticmethod
    def _capture_scan_findings(db, scan: RepoScan, findings: list[dict]) -> int:
        """Route scan findings into the same human-review queue as remediation
        side-discoveries; returns the number attributed to this scan so far."""
        for finding in findings:
            title = (finding.get("title") or "").strip()
            if not title:
                continue
            duplicate = db.scalar(
                select(DiscoveredIssue).where(
                    DiscoveredIssue.repo_full_name == scan.repo_full_name,
                    DiscoveredIssue.title == title,
                )
            )
            if duplicate is not None:
                continue
            db.add(
                DiscoveredIssue(
                    remediation_id=0,
                    scan_id=scan.id,
                    repo_full_name=scan.repo_full_name,
                    source_issue_number=0,
                    title=title,
                    description=finding.get("description", ""),
                    severity=finding.get("severity", "medium"),
                )
            )
        db.flush()
        return db.scalar(
            select(func.count()).select_from(DiscoveredIssue).where(DiscoveredIssue.scan_id == scan.id)
        ) or 0

    @staticmethod
    def _capture_discovered_issues(db, record: Remediation, findings: list[dict]) -> None:
        """Persist agent-surfaced side findings as proposals for human review.

        Dedupe by (repo, title): the poller sees the same structured output on
        every cycle until the session exits, and different sessions can trip
        over the same underlying defect.
        """
        for finding in findings:
            title = (finding.get("title") or "").strip()
            if not title:
                continue
            duplicate = db.scalar(
                select(DiscoveredIssue).where(
                    DiscoveredIssue.repo_full_name == record.repo_full_name,
                    DiscoveredIssue.title == title,
                )
            )
            if duplicate is not None:
                continue
            db.add(
                DiscoveredIssue(
                    remediation_id=record.id,
                    repo_full_name=record.repo_full_name,
                    source_issue_number=record.issue_number,
                    title=title,
                    description=finding.get("description", ""),
                    severity=finding.get("severity", "medium"),
                )
            )

    @staticmethod
    def _terminal_state(record: Remediation) -> str:
        if record.outcome in ("cannot_reproduce", "blocked"):
            return "escalated"
        if record.pr_url:
            # auto_merge repos still surface as merged-pending-CI; the PR link
            # is the audit trail either way.
            return "merged" if record.merge_policy == "auto_merge" else "awaiting_review"
        # Session finished but produced no PR: treat as failure, not success —
        # honest failure signals are the point of the report.
        return "failed" if record.outcome != "fixed" else "awaiting_review"
