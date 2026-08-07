"""The Remediation row is the single source of truth for one issue -> one
Devin session -> one PR. Every dashboard number is derived from this table,
so the report can always be regenerated from scratch.
"""

from __future__ import annotations

import time

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Remediation(Base):
    __tablename__ = "remediations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    repo_full_name: Mapped[str] = mapped_column(String(200), index=True)
    issue_number: Mapped[int] = mapped_column(Integer, index=True)
    issue_title: Mapped[str] = mapped_column(Text, default="")
    issue_url: Mapped[str] = mapped_column(Text, default="")
    issue_labels: Mapped[str] = mapped_column(Text, default="")  # comma separated

    session_id: Mapped[str] = mapped_column(String(100), default="", index=True)
    session_url: Mapped[str] = mapped_column(Text, default="")

    # Lifecycle: queued -> running -> awaiting_review | merged | failed | escalated
    # "awaiting_review" means Devin finished and a human decision is pending —
    # the state leadership sees as "waiting on us, not on the machine".
    state: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    # Raw Devin status/status_detail kept verbatim for the technical audit view.
    devin_status: Mapped[str] = mapped_column(String(40), default="")
    devin_status_detail: Mapped[str] = mapped_column(String(60), default="")

    outcome: Mapped[str] = mapped_column(String(40), default="")  # from structured output
    root_cause: Mapped[str] = mapped_column(Text, default="")
    tests_run: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[str] = mapped_column(String(20), default="")

    pr_url: Mapped[str] = mapped_column(Text, default="")
    pr_state: Mapped[str] = mapped_column(String(30), default="")

    acus_consumed: Mapped[float] = mapped_column(Float, default=0.0)
    # Snapshot of the repo's baseline at creation time so later config edits
    # don't silently rewrite historical ROI numbers.
    baseline_hours: Mapped[float] = mapped_column(Float, default=4.0)
    merge_policy: Mapped[str] = mapped_column(String(20), default="review")

    # How many automated unblock nudges we've sent; bounded to avoid loops.
    nudge_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    updated_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    completed_at: Mapped[int] = mapped_column(Integer, default=0)

    def touch(self) -> None:
        self.updated_at = int(time.time())
