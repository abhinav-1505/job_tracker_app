from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy.orm import Session

from job_tracker.db import SessionLocal


@contextmanager
def session_scope() -> Session:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

