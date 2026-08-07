"""Processed GitHub delivery IDs — GitHub redelivers webhooks (retries,
manual redelivery), and the unique delivery GUID is the only reliable way to
make ingestion exactly-once."""

from __future__ import annotations

import time

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    delivery_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
