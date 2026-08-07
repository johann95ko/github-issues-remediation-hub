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

from app.core.config import RepoConfig, find_repo_config
from app.models.remediation import Remediation
from app.services.devin_client import (
    REMEDIATION_OUTPUT_SCHEMA,
    DevinClientProtocol,
    build_remediation_prompt,
)

logger = logging.getLogger(__name__)

# States where a new event for the same issue must NOT spawn another session.
ACTIVE_STATES = ("queued", "running")


class Orchestrator:
    def __init__(self, devin: DevinClientProtocol) -> None:
        self._devin = devin

    def should_remediate(self, repo_full_name: str, labels: list[str]) -> RepoConfig | None:
        repo = find_repo_config(repo_full_name)
        if repo is None:
            logger.info("Ignoring event for unmonitored repo %s", repo_full_name)
            return None
        if not set(label.lower() for label in labels) & set(
            trigger.lower() for trigger in repo.trigger_labels
        ):
            logger.info(
                "Issue in %s lacks trigger labels %s", repo_full_name, repo.trigger_labels
            )
            return None
        return repo

    async def start_remediation(
        self,
        db: Session,
        repo: RepoConfig,
        issue_number: int,
        issue_title: str,
        issue_body: str,
        issue_url: str,
        labels: list[str],
    ) -> Remediation | None:
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
            baseline_hours=repo.baseline_engineer_hours_per_issue,
            merge_policy=repo.merge_policy,
            state="queued",
        )
        db.add(record)
        db.commit()

        payload = {
            "prompt": build_remediation_prompt(
                repo.full_name, issue_number, issue_title, issue_body, issue_url
            ),
            "title": f"Remediate {repo.full_name}#{issue_number}: {issue_title[:80]}",
            "tags": ["auto-remediation", f"issue-{issue_number}", repo.full_name.replace("/", "--")],
            "max_acu_limit": repo.max_acu_per_session,
            "structured_output_required": True,
            "structured_output_schema": REMEDIATION_OUTPUT_SCHEMA,
            # Disposable sessions: the PR is the artifact; keeping VMs resumable
            # for fire-and-forget remediation only adds cost.
            "resumable": False,
        }

        try:
            session = await self._devin.create_session(payload)
        except Exception:
            logger.exception("Failed to create Devin session for issue #%s", issue_number)
            record.state = "failed"
            record.outcome = "session_create_error"
            record.touch()
            db.commit()
            return record

        record.session_id = session["session_id"]
        record.session_url = session.get("url", "")
        record.state = "running"
        record.devin_status = session.get("status", "running")
        record.touch()
        db.commit()
        logger.info("Started session %s for issue #%s", record.session_id, issue_number)
        return record
