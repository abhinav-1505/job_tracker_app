from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from job_tracker.config import settings
from job_tracker.db_session import session_scope
from job_tracker.models import Application, Company, Job, Stage
from job_tracker.repositories import create_application, create_company, create_job, create_note, ensure_default_stages


def _wishlist_stage_id(db) -> int:
    ensure_default_stages(db)
    s = db.scalar(select(Stage).where(func.lower(Stage.name) == "wishlist"))
    if not s:
        s = db.scalar(select(Stage).order_by(Stage.position.asc()))
    if not s:
        raise HTTPException(status_code=500, detail="No pipeline stages configured")
    return s.id


def _find_company(db, name: str) -> Company | None:
    n = name.strip()
    if not n:
        return None
    return db.scalar(select(Company).where(func.lower(Company.name) == func.lower(n)))


def _find_job_by_url(db, company_id: int, job_url: str | None) -> Job | None:
    if not job_url or not job_url.strip():
        return None
    return db.scalar(select(Job).where(Job.company_id == company_id, Job.job_url == job_url.strip()))


def _find_job_by_title(db, company_id: int, title: str) -> Job | None:
    return db.scalar(select(Job).where(Job.company_id == company_id, Job.title == title.strip()))


def _first_application(db, job_id: int) -> Application | None:
    return db.scalar(select(Application).where(Application.job_id == job_id).limit(1))


class CaptureBody(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=200)
    job_title: str = Field(..., min_length=1, max_length=200)
    job_url: str | None = Field(None, max_length=800)
    page_title: str | None = Field(None, max_length=500)
    location: str | None = Field(None, max_length=200)
    notes: str | None = Field(None, max_length=8000)


class CaptureResponse(BaseModel):
    ok: bool = True
    duplicate: bool = False
    company_id: int
    job_id: int
    application_id: int
    message: str = ""


def verify_bearer(authorization: str | None) -> None:
    expected = (settings.capture_api_token or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="CAPTURE_API_TOKEN not set in .env")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Bearer token")
    token = authorization.split(None, 1)[1].strip()
    if token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def create_capture_app() -> FastAPI:
    app = FastAPI(title="Job Tracker Capture API", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/capture", response_model=CaptureResponse)
    def capture_job(
        body: CaptureBody,
        authorization: Annotated[str | None, Header()] = None,
    ) -> CaptureResponse:
        verify_bearer(authorization)
        with session_scope() as db:
            wishlist_id = _wishlist_stage_id(db)

            company = _find_company(db, body.company_name)
            if not company:
                company = create_company(db, body.company_name)
            db.flush()

            job = _find_job_by_url(db, company.id, body.job_url)
            if not job:
                job = _find_job_by_title(db, company.id, body.job_title)

            if job:
                existing = _first_application(db, job.id)
                if existing:
                    db.flush()
                    return CaptureResponse(
                        duplicate=True,
                        company_id=company.id,
                        job_id=job.id,
                        application_id=existing.id,
                        message="Already tracked (application exists for this job).",
                    )
                if body.job_url and not job.job_url:
                    job.job_url = body.job_url.strip()
                app_row = create_application(
                    db,
                    job_id=job.id,
                    stage_id=wishlist_id,
                    source="chrome-extension",
                )
                note_bits: list[str] = []
                if body.page_title:
                    note_bits.append(f"Page title: {body.page_title}")
                if body.notes:
                    note_bits.append(body.notes)
                if note_bits:
                    create_note(db, app_row.id, "\n\n".join(note_bits))
                db.flush()
                return CaptureResponse(
                    company_id=company.id,
                    job_id=job.id,
                    application_id=app_row.id,
                    message="Linked to existing job; application created.",
                )

            job = create_job(
                db,
                company_id=company.id,
                title=body.job_title.strip(),
                location=body.location,
                job_url=body.job_url.strip() if body.job_url else None,
                description=body.notes,
            )
            app_row = create_application(
                db,
                job_id=job.id,
                stage_id=wishlist_id,
                source="chrome-extension",
            )
            if body.page_title:
                create_note(db, app_row.id, f"Captured from Chrome.\nPage title: {body.page_title}")
            db.flush()

            return CaptureResponse(
                company_id=company.id,
                job_id=job.id,
                application_id=app_row.id,
                message="Saved to Wishlist.",
            )

    return app
