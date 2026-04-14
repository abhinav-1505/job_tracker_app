from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from job_tracker.config import settings


class Base(DeclarativeBase):
    pass


def make_engine():
    connect_args = {}
    if settings.db_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_engine(settings.db_url, future=True, echo=False, connect_args=connect_args)


ENGINE = make_engine()
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False, future=True)

