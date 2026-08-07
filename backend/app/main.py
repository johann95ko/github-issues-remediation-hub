"""Application entrypoint: wires the webhook ingress, the orchestrator, the
background poller, and the static dashboard into one deployable unit.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import admin, dashboard, webhooks
from app.core.config import get_settings
from app.core.db import init_db
from app.services.demo_client import DemoDevinClient
from app.services.devin_client import DevinClient
from app.services.orchestrator import Orchestrator
from app.services.poller import Poller

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _build_devin_client():
    settings = get_settings()
    if settings.demo_mode or not settings.devin_api_key:
        if not settings.demo_mode:
            logger.warning("DEVIN_API_KEY unset — falling back to demo simulator")
        return DemoDevinClient()
    return DevinClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    devin = _build_devin_client()
    app.state.orchestrator = Orchestrator(devin)
    poller = Poller(devin)
    poller.start()
    logger.info(
        "Remediation hub started (demo_mode=%s)", isinstance(devin, DemoDevinClient)
    )
    yield
    await poller.stop()
    if isinstance(devin, DevinClient):
        await devin.close()


app = FastAPI(title="Devin Remediation Hub", lifespan=lifespan)
app.include_router(webhooks.router)
app.include_router(dashboard.router)
app.include_router(admin.router)

# The built frontend is copied here by the Docker build; in local dev the
# Vite dev server proxies /api instead.
static_dir = Path(__file__).resolve().parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="dashboard")
