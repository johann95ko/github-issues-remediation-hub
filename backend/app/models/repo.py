"""Monitored repositories live in the database so technical users can connect
or tune a repository from the dashboard without touching config files or
redeploying. config/repos.yaml is read once, as a bootstrap seed, on first
startup with an empty table.
"""

from __future__ import annotations

import time

from sqlalchemy import Boolean, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class MonitoredRepo(Base):
    __tablename__ = "monitored_repos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    trigger_labels: Mapped[str] = mapped_column(String(400), default="devin-fix")  # comma separated
    merge_policy: Mapped[str] = mapped_column(String(20), default="review")
    max_acu_per_session: Mapped[int] = mapped_column(Integer, default=15)
    baseline_engineer_hours_per_issue: Mapped[float] = mapped_column(Float, default=4.0)
    # Pause switch: keeps history/config while ignoring new events.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))

    def labels_list(self) -> list[str]:
        return [x.strip() for x in self.trigger_labels.split(",") if x.strip()]
