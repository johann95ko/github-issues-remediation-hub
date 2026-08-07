"""In-process ingestion queue between the webhook handler and the Devin API.

The webhook handler must answer GitHub within its ~10s delivery timeout, but
creating a Devin session can take seconds (plus 429 backoff under burst).
Decoupling the two means a burst of hundreds of labeled issues is acknowledged
immediately and drained by a bounded worker pool. Queued records are persisted
first, so a restart re-launches anything the queue lost (see requeue_pending).
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.remediation import Remediation
from app.services.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

WORKERS = 4


class IngestQueue:
    def __init__(self, orchestrator: Orchestrator) -> None:
        self._orchestrator = orchestrator
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        self._requeue_pending()
        self._tasks = [asyncio.create_task(self._worker()) for _ in range(WORKERS)]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()

    def submit(self, remediation_id: int) -> None:
        self._queue.put_nowait(remediation_id)

    def _requeue_pending(self) -> None:
        # Records stuck in "queued" without a session are launches the process
        # lost (crash/restart between accept and create) — pick them back up.
        with SessionLocal() as db:
            pending = db.scalars(
                select(Remediation.id).where(
                    Remediation.state == "queued", Remediation.session_id == ""
                )
            ).all()
        for remediation_id in pending:
            self._queue.put_nowait(remediation_id)
        if pending:
            logger.info("Requeued %d pending remediation launches", len(pending))

    async def _worker(self) -> None:
        while True:
            remediation_id = await self._queue.get()
            try:
                with SessionLocal() as db:
                    record = db.get(Remediation, remediation_id)
                    if record is not None and record.state == "queued" and not record.session_id:
                        await self._orchestrator.launch_remediation(db, record)
            except Exception:
                logger.exception("Failed to launch remediation %d", remediation_id)
            finally:
                self._queue.task_done()
