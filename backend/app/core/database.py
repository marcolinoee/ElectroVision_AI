"""SQLAlchemy 2.0 Async & Sync database engine and session factories."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ElectroVision AI ORM models."""


def build_async_engine(database_url: str | None = None) -> AsyncEngine:
    settings = get_settings()
    url = database_url or settings.database_url
    kwargs: dict[str, object] = {"echo": False, "future": True}
    if not url.startswith("sqlite"):
        kwargs["pool_size"] = settings.db_pool_size
        kwargs["max_overflow"] = settings.db_max_overflow
        kwargs["pool_pre_ping"] = True
    return create_async_engine(url, **kwargs)


def build_sync_session_factory(database_sync_url: str | None = None) -> sessionmaker[Session]:
    """Build synchronous SQLAlchemy sessionmaker for Celery workers and CLI scripts."""
    settings = get_settings()
    url = database_sync_url or settings.database_sync_url
    engine = create_engine(url, pool_pre_ping=True, future=True)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


_engine: AsyncEngine | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_async_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = build_async_engine()
    return _engine


def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            bind=get_async_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    return _async_session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an ACID transactional AsyncSession."""
    session_factory = get_async_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
