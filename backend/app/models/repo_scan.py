"""A RepoScan is a human-initiated, read-only Devin audit of a connected
repository. Its only output is findings routed into the same review queue as
remediation side-discoveries — a scan never changes code or files issues.
"""

from __future__ import annotations

import time

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RepoScan(Base):
    __tablename__ = "repo_scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo_full_name: Mapped[str] = mapped_column(String(200), index=True)

    session_id: Mapped[str] = mapped_column(String(100), default="", index=True)
    session_url: Mapped[str] = mapped_column(Text, default="")

    # Lifecycle: queued -> running -> completed | failed
    state: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    devin_status: Mapped[str] = mapped_column(String(40), default="")
    devin_status_detail: Mapped[str] = mapped_column(String(60), default="")

    summary: Mapped[str] = mapped_column(Text, default="")
    findings_count: Mapped[int] = mapped_column(Integer, default=0)
    acus_consumed: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    updated_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    completed_at: Mapped[int] = mapped_column(Integer, default=0)

    def touch(self) -> None:
        self.updated_at = int(time.time())
