from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_tracker.models import Application, Company, Job, Stage, TaskKind
from job_tracker.repositories import (
    create_application,
    create_company,
    create_contact,
    create_job,
    create_note,
    create_task,
    ensure_default_stages,
    get_company_by_name,
    get_job_by_company_and_title,
)


def ensure_demo_data(db: Session, owner_user_id: int, is_admin: bool = False) -> None:
    ensure_default_stages(db)
    existing_company_q = select(Company.id)
    if not is_admin:
        existing_company_q = existing_company_q.where(Company.owner_user_id == owner_user_id)
    if db.scalar(existing_company_q.limit(1)):
        return

    stages = {s.name: s.id for s in db.scalars(select(Stage))}
    now = datetime.now(timezone.utc)

    company_specs = [
        ("Microsoft", "https://careers.microsoft.com", "Hyderabad", "Big Tech"),
        ("Apple", "https://jobs.apple.com", "Bengaluru", "Big Tech"),
        ("Amazon", "https://www.amazon.jobs", "Bengaluru", "Big Tech"),
        ("Netflix", "https://jobs.netflix.com", "Remote", "Streaming"),
        ("Google", "https://careers.google.com", "Bengaluru", "Big Tech"),
        ("Meta", "https://www.metacareers.com", "London", "Big Tech"),
    ]

    companies: dict[str, Company] = {}
    for name, website, location, industry in company_specs:
        company = get_company_by_name(db, name, owner_user_id=None if is_admin else owner_user_id)
        if not company:
            company = create_company(db, name, website=website, location=location, industry=industry, owner_user_id=owner_user_id)
        companies[name] = company
    db.flush()

    create_contact(
        db,
        "Priya Recruiter",
        company_id=companies["Google"].id,
        title="Recruiter",
        email="priya@google.example",
        owner_user_id=owner_user_id,
    )
    create_contact(
        db,
        "Rahul Hiring Manager",
        company_id=companies["Microsoft"].id,
        title="Hiring Manager",
        email="rahul@microsoft.example",
        owner_user_id=owner_user_id,
    )
    create_contact(
        db,
        "Sara Recruiter",
        company_id=companies["Netflix"].id,
        title="Talent Partner",
        email="sara@netflix.example",
        owner_user_id=owner_user_id,
    )

    job_specs = [
        ("Microsoft", "Software Engineer II", "Hybrid", "₹28-38 LPA"),
        ("Google", "Software Engineer", "Hybrid", "₹35-55 LPA"),
        ("Amazon", "SDE I", "Onsite", "₹22-32 LPA"),
        ("Apple", "Backend Engineer", "Hybrid", "₹30-45 LPA"),
        ("Netflix", "Platform Engineer", "Remote", "₹45-70 LPA"),
        ("Meta", "Product Data Analyst", "Hybrid", "₹26-40 LPA"),
    ]

    created_jobs = []
    for company_name, title, remote_policy, compensation in job_specs:
        company = companies[company_name]
        job = get_job_by_company_and_title(db, company.id, title)
        if not job:
            job = create_job(
                db,
                company_id=company.id,
                title=title,
                location=company.location or "India",
                remote_policy=remote_policy,
                compensation=compensation,
                job_url=f"{company.website}/roles/{title.lower().replace(' ', '-')}",
                description=f"Demo seeded role for {company_name}.",
            )
        created_jobs.append(job)
    db.flush()

    app_exists_q = select(Application.id).join(Job, Application.job_id == Job.id).join(Company, Job.company_id == Company.id)
    if not is_admin:
        app_exists_q = app_exists_q.where(Company.owner_user_id == owner_user_id)
    if not db.scalar(app_exists_q.limit(1)):
        app1 = create_application(
            db,
            job_id=created_jobs[0].id,
            stage_id=stages.get("Applied") or list(stages.values())[0],
            source="LinkedIn",
            applied_on=now.date(),
            next_follow_up_at=now + timedelta(days=3),
            priority=3,
        )
        create_note(db, app1.id, "Seeded demo application for Microsoft.")
        t1 = create_task(
            db,
            application_id=app1.id,
            title="Follow up with recruiter",
            due_at=now + timedelta(days=3),
            remind_at=now + timedelta(days=3, hours=-2),
        )
        t1.is_important = True

        app2 = create_application(
            db,
            job_id=created_jobs[1].id,
            stage_id=stages.get("Interview") or list(stages.values())[0],
            source="Referral",
            applied_on=(now - timedelta(days=10)).date(),
            next_follow_up_at=now + timedelta(days=1),
            priority=4,
        )
        create_note(db, app2.id, "System design round scheduled.")
        e1 = create_task(
            db,
            application_id=app2.id,
            title="Google interview",
            due_at=now + timedelta(days=1),
            remind_at=now + timedelta(hours=8),
        )
        e1.kind = TaskKind.event
        e1.is_important = True

