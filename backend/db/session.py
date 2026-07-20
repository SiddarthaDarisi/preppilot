"""DB engine / session factory / init."""
from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config import get_settings
from backend.db.models import Base

logger = logging.getLogger("preppilot.db")

_settings = get_settings()

engine = create_engine(
    _settings.db.url,
    connect_args={"check_same_thread": False} if _settings.db.url.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _migrate_add_column(table: str, column: str, ddl_type: str) -> None:
    """Best-effort additive column migration (the project's first mini-migration
    — see CLAUDE.md). `create_all()` only creates missing tables, not missing
    columns on tables that already exist, so a pre-existing DB from before a
    column was added needs this. No-op (silently) if the column is already
    there or the backend doesn't support this exact ALTER syntax."""
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
    except Exception:
        pass


def init_db() -> None:
    """Create all tables (idempotent)."""
    Base.metadata.create_all(engine)
    _migrate_add_column("sessions", "mode", "VARCHAR(20) DEFAULT 'adaptive'")
    _migrate_add_column("sessions", "persona", "VARCHAR(20) DEFAULT 'neutral'")
    logger.info("Database initialized at %s", _settings.db.url)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
