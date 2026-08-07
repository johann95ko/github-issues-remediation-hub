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
    from app.models import discovered_issue, remediation, repo  # noqa: F401

    Base.metadata.create_all(engine)
    _migrate_columns()
    _seed_repos_from_yaml()


def _migrate_columns() -> None:
    # create_all only creates missing tables; columns added to existing tables
    # need explicit ALTERs. Enough for SQLite in lieu of a migration framework.
    from sqlalchemy import text

    additions = {
        "remediations": {
            "problem_summary": "TEXT DEFAULT ''",
            "fix_summary": "TEXT DEFAULT ''",
        },
    }
    with engine.begin() as conn:
        for table, columns in additions.items():
            existing = {
                row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))
            }
            for column, ddl in columns.items():
                if column not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def _seed_repos_from_yaml() -> None:
    # YAML is bootstrap-only: it populates an empty table on first boot, then
    # the UI owns the config. Never overwrite user edits made via the UI.
    from app.core.config import get_repo_configs
    from app.models.repo import MonitoredRepo

    with SessionLocal() as db:
        if db.query(MonitoredRepo).count() > 0:
            return
        for cfg in get_repo_configs():
            db.add(
                MonitoredRepo(
                    full_name=cfg.full_name,
                    trigger_labels=",".join(cfg.trigger_labels),
                    merge_policy=cfg.merge_policy,
                    max_acu_per_session=cfg.max_acu_per_session,
                    baseline_engineer_hours_per_issue=cfg.baseline_engineer_hours_per_issue,
                )
            )
        db.commit()


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
