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

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.discovered_issue import DiscoveredIssue
from app.models.remediation import Remediation
from app.services.devin_client import DevinClientProtocol

logger = logging.getLogger(__name__)

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
        db = SessionLocal()
        try:
            active = list(
                db.scalars(
                    select(Remediation).where(
                        Remediation.state == "running", Remediation.session_id != ""
                    )
                )
            )
            for record in active:
                await self._sync_record(db, record)
        finally:
            db.close()

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
            if record.nudge_count < MAX_NUDGES:
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
