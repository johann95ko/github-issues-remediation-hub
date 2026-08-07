"""SQLite persistence.

SQLite is deliberate: the hub's write volume is one row per remediation plus
periodic status updates, so a zero-ops embedded database keeps the Docker
story to a single container + volume. The SQLAlchemy layer means swapping to
Postgres later is a connection-string change.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = get_settings().database_url
    if url.startswith("sqlite"):
        db_path = url.split("///")[-1]
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: FastAPI handlers and the poller share the pool
    # across threads; SQLAlchemy's pooling serializes access safely.
    return create_engine(url, connect_args={"check_same_thread": False})


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    from app.models import remediation  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
