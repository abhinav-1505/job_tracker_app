from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_tracker.models import (
    Application,
    ApplicationStageEvent,
    Attachment,
    Company,
    Contact,
    Job,
    Note,
    Stage,
    Task,
    User,
)
from job_tracker.services.auth import hash_password, make_password_salt, verify_password


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def touch_application_activity(db: Session, application_id: int) -> None:
    app = db.get(Application, application_id)
    if not app:
        return
    app.last_activity_at = utcnow()


def set_application_stage(db: Session, application_id: int, to_stage_id: int) -> None:
    app = db.get(Application, application_id)
    if not app:
        raise ValueError("Application not found")
    from_stage_id = app.stage_id
    if from_stage_id == to_stage_id:
        return
    app.stage_id = to_stage_id
    app.last_activity_at = utcnow()
    db.add(
        ApplicationStageEvent(
            application_id=application_id,
            from_stage_id=from_stage_id,
            to_stage_id=to_stage_id,
        )
    )


def list_stages(db: Session) -> list[Stage]:
    return list(db.scalars(select(Stage).order_by(Stage.position.asc(), Stage.name.asc())))


def ensure_default_stages(db: Session) -> None:
    existing = list_stages(db)
    if existing:
        return
    defaults = [
        ("Wishlist", 0, False),
        ("Applied", 10, False),
        ("Screen", 20, False),
        ("Interview", 30, False),
        ("Offer", 40, True),
        ("Rejected", 50, True),
        ("Accepted", 60, True),
    ]
    for name, pos, terminal in defaults:
        db.add(Stage(name=name, position=pos, is_terminal=terminal))


def create_company(
    db: Session,
    name: str,
    website: str | None = None,
    location: str | None = None,
    industry: str | None = None,
    owner_user_id: int | None = None,
) -> Company:
    c = Company(name=name.strip(), website=website, location=location, industry=industry, owner_user_id=owner_user_id)
    db.add(c)
    return c


def get_company_by_name(db: Session, name: str, owner_user_id: int | None = None) -> Company | None:
    q = select(Company).where(Company.name == name.strip())
    if owner_user_id is not None:
        q = q.where(Company.owner_user_id == owner_user_id)
    return db.scalar(q)


def create_job(
    db: Session,
    company_id: int,
    title: str,
    location: str | None = None,
    employment_type: str | None = None,
    remote_policy: str | None = None,
    job_url: str | None = None,
    compensation: str | None = None,
    description: str | None = None,
) -> Job:
    j = Job(
        company_id=company_id,
        title=title.strip(),
        location=location,
        employment_type=employment_type,
        remote_policy=remote_policy,
        job_url=job_url,
        compensation=compensation,
        description=description,
    )
    db.add(j)
    return j


def get_job_by_company_and_title(db: Session, company_id: int, title: str) -> Job | None:
    return db.scalar(select(Job).where(Job.company_id == company_id, Job.title == title.strip()))


def create_contact(
    db: Session,
    name: str,
    company_id: int | None = None,
    title: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    linkedin: str | None = None,
    notes: str | None = None,
    owner_user_id: int | None = None,
) -> Contact:
    c = Contact(
        name=name.strip(),
        owner_user_id=owner_user_id,
        company_id=company_id,
        title=title,
        email=email,
        phone=phone,
        linkedin=linkedin,
        notes=notes,
    )
    db.add(c)
    return c


def create_application(
    db: Session,
    job_id: int,
    stage_id: int,
    primary_contact_id: int | None = None,
    source: str | None = None,
    applied_on=None,
    next_follow_up_at=None,
    priority: int = 0,
) -> Application:
    a = Application(
        job_id=job_id,
        stage_id=stage_id,
        primary_contact_id=primary_contact_id,
        source=source,
        applied_on=applied_on,
        next_follow_up_at=next_follow_up_at,
        priority=priority,
        last_activity_at=utcnow(),
    )
    db.add(a)
    db.add(ApplicationStageEvent(application=a, from_stage_id=None, to_stage_id=stage_id))
    # Ensure `a.id` is available immediately for creating related records (notes/tasks/attachments),
    # especially during seeding flows that create children before the outer commit.
    db.flush()
    return a


def create_task(
    db: Session,
    application_id: int,
    title: str,
    description: str | None = None,
    due_at=None,
    remind_at=None,
    is_recurring: bool = False,
    recurring_rule: str | None = None,
) -> Task:
    t = Task(
        application_id=application_id,
        title=title.strip(),
        description=description,
        due_at=due_at,
        remind_at=remind_at,
        is_recurring=is_recurring,
        recurring_rule=recurring_rule,
    )
    db.add(t)
    touch_application_activity(db, application_id)
    return t


def create_note(db: Session, application_id: int, body: str) -> Note:
    n = Note(application_id=application_id, body=body)
    db.add(n)
    touch_application_activity(db, application_id)
    return n


def create_attachment(
    db: Session,
    application_id: int,
    kind,
    original_filename: str,
    stored_path: str,
    content_type: str | None = None,
    size_bytes: int | None = None,
) -> Attachment:
    a = Attachment(
        application_id=application_id,
        kind=kind,
        original_filename=original_filename,
        stored_path=stored_path,
        content_type=content_type,
        size_bytes=size_bytes,
    )
    db.add(a)
    touch_application_activity(db, application_id)
    return a


def user_count(db: Session) -> int:
    from sqlalchemy import func as _func

    return int(db.scalar(select(_func.count(User.id))) or 0)


def create_user(db: Session, username: str, password: str, is_admin: bool = False) -> User:
    u = User(
        username=username.strip(),
        is_admin=is_admin,
        password_salt=make_password_salt(),
        password_hash="",
    )
    u.password_hash = hash_password(password=password, salt_hex=u.password_salt)
    db.add(u)
    return u


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    u = db.scalar(select(User).where(User.username == username.strip()))
    if not u:
        return None
    if verify_password(password=password, salt_hex=u.password_salt, password_hash_hex=u.password_hash):
        return u
    return None

