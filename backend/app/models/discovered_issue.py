"""Issues Devin surfaces while investigating something else.

Agents routinely notice adjacent defects mid-investigation. Discarding those
observations wastes the most expensive part of the work, but letting an agent
file issues unsupervised invites noise — so findings land here as proposals
and a human promotes them to real GitHub issues (one click) or dismisses them.
"""

from __future__ import annotations

import time

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class DiscoveredIssue(Base):
    __tablename__ = "discovered_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Which remediation surfaced this finding (provenance for the audit trail).
    remediation_id: Mapped[int] = mapped_column(Integer, index=True)
    # Set when the finding came from a manual repository scan rather than a
    # remediation side-discovery (exactly one of the two sources applies).
    scan_id: Mapped[int] = mapped_column(Integer, default=0, index=True)
    repo_full_name: Mapped[str] = mapped_column(String(200), index=True)
    source_issue_number: Mapped[int] = mapped_column(Integer, default=0)

    title: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(20), default="medium")  # low|medium|high

    # proposed -> filed | dismissed
    status: Mapped[str] = mapped_column(String(20), default="proposed", index=True)
    filed_issue_url: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
