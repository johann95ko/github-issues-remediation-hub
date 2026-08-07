"""GitHub webhook ingress — the event trigger for the whole system."""

from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

# Issue actions that can qualify an issue for remediation. "labeled" matters
# because the trigger label is often added after the issue is opened.
QUALIFYING_ACTIONS = {"opened", "labeled", "reopened"}


def _verify_signature(secret: str, body: bytes, signature_header: str | None) -> None:
    # Anyone on the internet can POST to a public webhook URL; the HMAC check
    # is the only thing standing between that and ACU spend.
    if not secret:
        logger.warning("GITHUB_WEBHOOK_SECRET unset — accepting unsigned webhook (dev only)")
        return
    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing webhook signature")
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


@router.post("/webhooks/github")
async def github_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
):
    body = await request.body()
    _verify_signature(get_settings().github_webhook_secret, body, x_hub_signature_256)

    if x_github_event != "issues":
        return {"status": "ignored", "reason": f"event {x_github_event} not handled"}

    payload = await request.json()
    action = payload.get("action", "")
    if action not in QUALIFYING_ACTIONS:
        return {"status": "ignored", "reason": f"action {action} not qualifying"}

    issue = payload.get("issue") or {}
    repo_full_name = (payload.get("repository") or {}).get("full_name", "")
    labels = [label.get("name", "") for label in issue.get("labels", [])]

    orchestrator = request.app.state.orchestrator
    repo = orchestrator.should_remediate(db, repo_full_name, labels)
    if repo is None:
        return {"status": "ignored", "reason": "repo not monitored or labels do not qualify"}

    record = await orchestrator.start_remediation(
        db,
        repo,
        issue_number=issue.get("number", 0),
        issue_title=issue.get("title", ""),
        issue_body=issue.get("body") or "",
        issue_url=issue.get("html_url", ""),
        labels=labels,
    )
    if record is None:
        return {"status": "duplicate", "reason": "active remediation already exists"}
    return {
        "status": "accepted",
        "remediation_id": record.id,
        "session_id": record.session_id,
        "session_url": record.session_url,
    }
