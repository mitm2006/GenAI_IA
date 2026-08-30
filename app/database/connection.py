"""SQLAlchemy engine and session management.

Supports both PostgreSQL and SQLite. Defaults to SQLite for local development
when PostgreSQL is not available.
"""

import os
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker, Session
from loguru import logger

from app.config import settings


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _build_engine(url: str, **kwargs):
    """Build an engine with appropriate settings for the database type."""
    if _is_sqlite(url):
        # SQLite-specific settings
        engine = create_engine(
            url,
            echo=settings.debug,
            connect_args={"check_same_thread": False},
        )
        # Enable WAL mode and foreign keys for SQLite
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine
    else:
        return create_engine(
            url,
            pool_size=kwargs.get("pool_size", 5),
            max_overflow=kwargs.get("max_overflow", 10),
            pool_pre_ping=True,
            echo=settings.debug,
        )


# ── Engines ───────────────────────────────────────────────────
_rw_engine = _build_engine(settings.database_url, pool_size=5, max_overflow=10)
_ro_engine = _build_engine(settings.db_readonly_url, pool_size=10, max_overflow=20)

RWSession = sessionmaker(bind=_rw_engine)
ROSession = sessionmaker(bind=_ro_engine)


def get_rw_session() -> Session:
    """Return a read-write session (for seeding data)."""
    session = RWSession()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_ro_session() -> Session:
    """Return a read-only session with statement timeout."""
    session = ROSession()
    try:
        if not _is_sqlite(settings.db_readonly_url):
            timeout_ms = settings.query_timeout_seconds * 1000
            session.execute(text(f"SET statement_timeout = {timeout_ms}"))
        yield session
    finally:
        session.close()


def get_rw_engine():
    """Return the read-write engine for DDL / bulk operations."""
    return _rw_engine


def get_ro_engine():
    """Return the read-only engine."""
    return _ro_engine
