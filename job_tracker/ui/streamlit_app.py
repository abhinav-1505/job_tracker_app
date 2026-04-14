from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from job_tracker.config import settings
from job_tracker.db import ENGINE
from job_tracker.db_session import session_scope
from job_tracker.models import (
    Application,
    ApplicationStatus,
    AttachmentKind,
    Company,
    Contact,
    Job,
    Note,
    Stage,
    Task,
    TaskKind,
    TaskStatus,
)
from job_tracker.repositories import (
    create_application,
    create_attachment,
    create_company,
    create_contact,
    create_job,
    create_note,
    create_task,
    create_user,
    ensure_default_stages,
    list_stages,
    set_application_stage,
)
from job_tracker.services.demo_data import ensure_demo_data
from job_tracker.ui.auth import current_user_id, current_user_is_admin, logout_button, require_auth


ROOT = Path(__file__).resolve().parents[2]
UPLOADS_DIR = ROOT / "uploads"


def _as_utc_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    # SQLite can return naive datetimes; treat them as UTC for consistency.
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _app_header() -> None:
    st.set_page_config(page_title="Job Tracker", page_icon="🗂️", layout="wide")
    st.sidebar.title("Job Tracker")
    st.sidebar.caption("Personal ATS")
    if current_user_id() is not None:
        role = "admin" if current_user_is_admin() else "user"
        st.sidebar.write(f"User ID: `{current_user_id()}` ({role})")
    logout_button()


def _nav() -> str:
    return st.sidebar.radio(
        "Navigate",
        [
            "Dashboard",
            "Kanban Pipeline",
            "Applications",
            "Tasks & Calendar",
            "Companies",
            "Jobs",
            "Contacts",
            "Import/Export",
            "Analytics",
            "Settings",
        ],
    )


def _stage_map(db) -> dict[int, Stage]:
    return {s.id: s for s in list_stages(db)}


def _application_label(app: Application) -> str:
    title = app.job.title if app.job else f"Job {app.job_id}"
    company = app.job.company.name if app.job and app.job.company else ""
    return f"{title} — {company} (#{app.id})"


def _scope_company_query():
    q = select(Company)
    uid = current_user_id()
    if not current_user_is_admin() and uid is not None:
        q = q.where(Company.owner_user_id == uid)
    return q


def _scope_contacts_query():
    q = select(Contact)
    uid = current_user_id()
    if not current_user_is_admin() and uid is not None:
        q = q.where(Contact.owner_user_id == uid)
    return q


def _scoped_company_ids(db) -> list[int]:
    return [c.id for c in db.scalars(_scope_company_query())]


def _scope_jobs_query():
    q = select(Job).join(Company, Job.company_id == Company.id)
    uid = current_user_id()
    if not current_user_is_admin() and uid is not None:
        q = q.where(Company.owner_user_id == uid)
    return q


def _scope_applications_query():
    q = select(Application).join(Job, Application.job_id == Job.id).join(Company, Job.company_id == Company.id)
    uid = current_user_id()
    if not current_user_is_admin() and uid is not None:
        q = q.where(Company.owner_user_id == uid)
    return q


def page_dashboard() -> None:
    st.subheader("Dashboard")
    with session_scope() as db:
        ensure_default_stages(db)
        ensure_demo_data(db, owner_user_id=current_user_id() or 1, is_admin=current_user_is_admin())

        total_apps = db.scalar(select(func.count()).select_from(_scope_applications_query().subquery())) or 0
        total_companies = db.scalar(select(func.count()).select_from(_scope_company_query().subquery())) or 0
        open_tasks = db.scalar(select(func.count(Task.id)).where(Task.status == TaskStatus.open)) or 0
        important_items = db.scalar(
            select(func.count(Task.id)).where(Task.status == TaskStatus.open).where(Task.is_important.is_(True))
        ) or 0
        upcoming = list(
            db.scalars(
                select(Task)
                .where(Task.status == TaskStatus.open)
                .where(Task.due_at.is_not(None))
                .order_by(Task.due_at.asc())
                .limit(10)
            )
        )
        recent_companies = list(db.scalars(_scope_company_query().order_by(Company.created_at.desc()).limit(8)))

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Applications", total_apps)
        c2.metric("Open tasks", open_tasks)
        c3.metric("Companies", total_companies)
        c4.metric("Important", important_items)

        st.markdown("### Companies")
        if recent_companies:
            st.write(", ".join([c.name for c in recent_companies]))
        else:
            st.caption("No companies yet.")

        st.markdown("### Upcoming tasks")
        if not upcoming:
            st.info("No upcoming tasks.")
        else:
            rows = []
            for t in upcoming:
                rows.append(
                    {
                        "id": t.id,
                        "title": t.title,
                        "kind": t.kind.value if hasattr(t.kind, "value") else str(t.kind),
                        "important": t.is_important,
                        "due_at": t.due_at,
                        "remind_at": t.remind_at,
                        "application_id": t.application_id,
                    }
                )
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def page_companies() -> None:
    st.subheader("Companies")
    with session_scope() as db:
        companies = list(db.scalars(_scope_company_query().order_by(Company.name.asc())))
        st.markdown("### Add company")
        with st.form("add_company", clear_on_submit=True):
            name = st.text_input("Name", max_chars=200)
            website = st.text_input("Website")
            location = st.text_input("Location")
            industry = st.text_input("Industry")
            submitted = st.form_submit_button("Create", type="primary")
            if submitted:
                if not name.strip():
                    st.error("Name is required.")
                else:
                    create_company(
                        db,
                        name=name,
                        website=website or None,
                        location=location or None,
                        industry=industry or None,
                        owner_user_id=current_user_id(),
                    )
                    db.commit()
                    st.success("Created.")
                    st.rerun()

        st.markdown("### List")
        if not companies:
            st.info("No companies yet.")
            return
        df = pd.DataFrame(
            [{"id": c.id, "name": c.name, "website": c.website, "location": c.location, "industry": c.industry} for c in companies]
        )
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.markdown("### Edit / delete")
        company_id = st.selectbox("Select company", [c.id for c in companies], format_func=lambda cid: next(c.name for c in companies if c.id == cid))
        c = db.get(Company, company_id)
        if not c:
            return
        with st.form("edit_company"):
            name = st.text_input("Name", value=c.name)
            website = st.text_input("Website", value=c.website or "")
            location = st.text_input("Location", value=c.location or "")
            industry = st.text_input("Industry", value=c.industry or "")
            col1, col2 = st.columns(2)
            with col1:
                save = st.form_submit_button("Save", type="primary")
            with col2:
                delete = st.form_submit_button("Delete", type="secondary")
            if save:
                c.name = name.strip()
                c.website = website or None
                c.location = location or None
                c.industry = industry or None
                db.commit()
                st.success("Saved.")
                st.rerun()
            if delete:
                db.delete(c)
                db.commit()
                st.warning("Deleted.")
                st.rerun()


def page_jobs() -> None:
    st.subheader("Jobs")
    with session_scope() as db:
        ensure_demo_data(db, owner_user_id=current_user_id() or 1, is_admin=current_user_is_admin())
        companies = list(db.scalars(_scope_company_query().order_by(Company.name.asc())))
        jobs = list(db.scalars(_scope_jobs_query().options(joinedload(Job.company)).order_by(Job.created_at.desc())))

        st.markdown("### Add job")
        if not companies:
            st.info("Create a company first.")
        else:
            with st.form("add_job", clear_on_submit=True):
                company_id = st.selectbox("Company", [c.id for c in companies], format_func=lambda cid: next(c.name for c in companies if c.id == cid))
                title = st.text_input("Title")
                location = st.text_input("Location")
                employment_type = st.text_input("Employment type")
                remote_policy = st.text_input("Remote policy")
                job_url = st.text_input("Job URL")
                compensation = st.text_input("Compensation")
                description = st.text_area("Description")
                submitted = st.form_submit_button("Create", type="primary")
                if submitted:
                    if not title.strip():
                        st.error("Title is required.")
                    else:
                        create_job(
                            db,
                            company_id=company_id,
                            title=title,
                            location=location or None,
                            employment_type=employment_type or None,
                            remote_policy=remote_policy or None,
                            job_url=job_url or None,
                            compensation=compensation or None,
                            description=description or None,
                        )
                        db.commit()
                        st.success("Created.")
                        st.rerun()

        st.markdown("### List")
        if jobs:
            df = pd.DataFrame(
                [
                    {
                        "id": j.id,
                        "company": j.company.name if j.company else "",
                        "title": j.title,
                        "location": j.location,
                        "remote_policy": j.remote_policy,
                        "job_url": j.job_url,
                    }
                    for j in jobs
                ]
            )
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No jobs yet.")


def page_contacts() -> None:
    st.subheader("Contacts")
    with session_scope() as db:
        companies = list(db.scalars(_scope_company_query().order_by(Company.name.asc())))
        contacts = list(db.scalars(_scope_contacts_query().options(joinedload(Contact.company)).order_by(Contact.created_at.desc())))

        st.markdown("### Add contact")
        with st.form("add_contact", clear_on_submit=True):
            name = st.text_input("Name")
            company_id = st.selectbox(
                "Company (optional)",
                [None] + [c.id for c in companies],
                format_func=lambda cid: "—" if cid is None else next(c.name for c in companies if c.id == cid),
            )
            title = st.text_input("Title")
            email = st.text_input("Email")
            phone = st.text_input("Phone")
            linkedin = st.text_input("LinkedIn")
            notes = st.text_area("Notes")
            submitted = st.form_submit_button("Create", type="primary")
            if submitted:
                if not name.strip():
                    st.error("Name is required.")
                else:
                    create_contact(
                        db,
                        name=name,
                        company_id=company_id,
                        title=title or None,
                        email=email or None,
                        phone=phone or None,
                        linkedin=linkedin or None,
                        notes=notes or None,
                        owner_user_id=current_user_id(),
                    )
                    st.success("Created.")
                    st.rerun()

        st.markdown("### List")
        if not contacts:
            st.info("No contacts yet.")
            return
        df = pd.DataFrame(
            [
                {
                    "id": c.id,
                    "name": c.name,
                    "company": c.company.name if c.company else "",
                    "title": c.title,
                    "email": c.email,
                    "phone": c.phone,
                    "linkedin": c.linkedin,
                }
                for c in contacts
            ]
        )
        st.dataframe(df, use_container_width=True, hide_index=True)


def page_applications() -> None:
    st.subheader("Applications")
    with session_scope() as db:
        ensure_default_stages(db)
        ensure_demo_data(db, owner_user_id=current_user_id() or 1, is_admin=current_user_is_admin())
        stages = list_stages(db)
        companies = list(db.scalars(_scope_company_query().order_by(Company.name.asc())))
        jobs = list(db.scalars(_scope_jobs_query().options(joinedload(Job.company)).order_by(Job.created_at.desc())))
        contacts = list(db.scalars(_scope_contacts_query().options(joinedload(Contact.company)).order_by(Contact.created_at.desc())))

        st.markdown("### Add application")
        if not jobs:
            st.info("Create a job first.")
        else:
            with st.form("add_application", clear_on_submit=True):
                job_id = st.selectbox("Job", [j.id for j in jobs], format_func=lambda jid: next(f"{j.title} — {j.company.name}" for j in jobs if j.id == jid))
                stage_id = st.selectbox("Stage", [s.id for s in stages], format_func=lambda sid: next(s.name for s in stages if s.id == sid))
                contact_id = st.selectbox(
                    "Primary contact (optional)",
                    [None] + [c.id for c in contacts],
                    format_func=lambda cid: "—" if cid is None else next(c.name for c in contacts if c.id == cid),
                )
                source = st.text_input("Source (optional)", placeholder="LinkedIn / Referral / Company site")
                applied_on = st.date_input("Applied on", value=None)
                priority = st.slider("Priority", min_value=0, max_value=5, value=2)
                follow = st.checkbox("Set follow-up reminder", value=True)
                next_follow_up_at = None
                if follow:
                    dt = st.date_input("Follow-up date", value=date.today() + timedelta(days=3))
                    next_follow_up_at = datetime(dt.year, dt.month, dt.day, 9, 0, tzinfo=timezone.utc)
                submitted = st.form_submit_button("Create", type="primary")
                if submitted:
                    create_application(
                        db,
                        job_id=job_id,
                        stage_id=stage_id,
                        primary_contact_id=contact_id,
                        source=source or None,
                        applied_on=applied_on,
                        next_follow_up_at=next_follow_up_at,
                        priority=priority,
                    )
                    db.commit()
                    st.success("Created.")
                    st.rerun()

        st.markdown("### List")
        apps = list(
            db.scalars(
                _scope_applications_query()
                .options(joinedload(Application.job).joinedload(Job.company), joinedload(Application.stage))
                .order_by(Application.updated_at.desc())
            )
        )
        if not apps:
            st.info("No applications yet.")
            return

        df = pd.DataFrame(
            [
                {
                    "id": a.id,
                    "company": a.job.company.name if a.job and a.job.company else "",
                    "job_title": a.job.title if a.job else "",
                    "stage": a.stage.name if a.stage else "",
                    "status": a.status.value if hasattr(a.status, "value") else str(a.status),
                    "applied_on": a.applied_on,
                    "next_follow_up_at": a.next_follow_up_at,
                    "last_activity_at": a.last_activity_at,
                }
                for a in apps
            ]
        )
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.markdown("### Application details")
        app_id = st.selectbox("Select application", [a.id for a in apps], format_func=lambda aid: next(_application_label(a) for a in apps if a.id == aid))
        app = db.get(Application, app_id)
        if not app:
            return

        app = db.scalar(
            select(Application)
            .where(Application.id == app_id)
            .options(
                joinedload(Application.job).joinedload(Job.company),
                joinedload(Application.stage),
                joinedload(Application.tasks),
                joinedload(Application.notes),
                joinedload(Application.attachments),
            )
        )
        if not app:
            return

        colA, colB = st.columns([2, 1])
        with colA:
            st.markdown("#### Summary")
            st.write(
                {
                    "company": app.job.company.name if app.job and app.job.company else "",
                    "job_title": app.job.title if app.job else "",
                    "stage": app.stage.name if app.stage else "",
                    "source": app.source,
                    "applied_on": app.applied_on,
                }
            )

            st.markdown("#### Notes")
            with st.form("add_note", clear_on_submit=True):
                body = st.text_area("Add a note", height=120)
                submitted = st.form_submit_button("Add note", type="primary")
                if submitted and body.strip():
                    create_note(db, app.id, body.strip())
                    db.commit()
                    st.success("Added.")
                    st.rerun()
            if app.notes:
                for n in sorted(app.notes, key=lambda x: x.created_at, reverse=True):
                    st.caption(n.created_at)
                    st.write(n.body)

            st.markdown("#### Attachments")
            UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
            with st.form("upload_attachment"):
                kind = st.selectbox("Kind", [k.value for k in AttachmentKind])
                up = st.file_uploader("Upload file", type=None)
                submitted = st.form_submit_button("Upload", type="primary")
                if submitted:
                    if not up:
                        st.error("Choose a file.")
                    else:
                        app_dir = UPLOADS_DIR / f"application_{app.id}"
                        app_dir.mkdir(parents=True, exist_ok=True)
                        safe_name = up.name.replace("\\", "_").replace("/", "_")
                        stored = app_dir / f"{int(datetime.now().timestamp())}_{safe_name}"
                        stored.write_bytes(up.getbuffer())
                        create_attachment(
                            db,
                            application_id=app.id,
                            kind=AttachmentKind(kind),
                            original_filename=up.name,
                            stored_path=str(stored.relative_to(ROOT)),
                            content_type=up.type,
                            size_bytes=stored.stat().st_size,
                        )
                        db.commit()
                        st.success("Uploaded.")
                        st.rerun()
            if app.attachments:
                att_rows = []
                for a in sorted(app.attachments, key=lambda x: x.uploaded_at, reverse=True):
                    att_rows.append(
                        {
                            "id": a.id,
                            "kind": a.kind.value if hasattr(a.kind, "value") else str(a.kind),
                            "filename": a.original_filename,
                            "path": a.stored_path,
                            "uploaded_at": a.uploaded_at,
                        }
                    )
                st.dataframe(pd.DataFrame(att_rows), use_container_width=True, hide_index=True)

        with colB:
            st.markdown("#### Tasks")
            with st.form("add_task", clear_on_submit=True):
                title = st.text_input("Title")
                description = st.text_area("Description", height=80)
                due = st.date_input("Due date", value=None)
                remind = st.checkbox("Email reminder", value=False)
                remind_at = None
                if remind:
                    rd = st.date_input("Remind on", value=date.today())
                    remind_at = datetime(rd.year, rd.month, rd.day, 9, 0, tzinfo=timezone.utc)
                recurring = st.checkbox("Recurring", value=False)
                recurring_rule = None
                if recurring:
                    recurring_rule = st.selectbox("Rule", ["daily", "weekly", "monthly"])
                submitted = st.form_submit_button("Add task", type="primary")
                if submitted:
                    if not title.strip():
                        st.error("Title is required.")
                    else:
                        due_at = None
                        if due:
                            due_at = datetime(due.year, due.month, due.day, 17, 0, tzinfo=timezone.utc)
                        create_task(
                            db,
                            application_id=app.id,
                            title=title,
                            description=description or None,
                            due_at=due_at,
                            remind_at=remind_at,
                            is_recurring=recurring,
                            recurring_rule=recurring_rule,
                        )
                        db.commit()
                        st.success("Added.")
                        st.rerun()

            if app.tasks:
                for t in sorted(
                    app.tasks,
                    key=lambda x: (
                        x.status != TaskStatus.open,
                        _as_utc_aware(x.due_at) or datetime.max.replace(tzinfo=timezone.utc),
                    ),
                ):
                    with st.container(border=True):
                        st.write(f"**{t.title}**")
                        if t.due_at:
                            st.caption(f"Due: {t.due_at}")
                        if t.remind_at:
                            st.caption(f"Remind: {t.remind_at}")
                        cols = st.columns(3)
                        with cols[0]:
                            if st.button("Done", key=f"task_done_{t.id}", use_container_width=True):
                                t.status = TaskStatus.done
                                t.completed_at = datetime.now(timezone.utc)
                                db.commit()
                                st.rerun()
                        with cols[1]:
                            if st.button("Snooze 1d", key=f"task_snooze_{t.id}", use_container_width=True):
                                t.snoozed_until = datetime.now(timezone.utc) + timedelta(days=1)
                                db.commit()
                                st.rerun()
                        with cols[2]:
                            if st.button("Delete", key=f"task_del_{t.id}", use_container_width=True):
                                db.delete(t)
                                db.commit()
                                st.rerun()


def page_kanban() -> None:
    st.subheader("Kanban Pipeline")
    st.caption("Move applications across stages.")
    with session_scope() as db:
        ensure_default_stages(db)
        ensure_demo_data(db, owner_user_id=current_user_id() or 1, is_admin=current_user_is_admin())
        stages = list_stages(db)
        stage_ids = [s.id for s in stages]
        stage_name = {s.id: s.name for s in stages}

        apps = list(
            db.scalars(
                select(Application)
                .options(joinedload(Application.job).joinedload(Job.company), joinedload(Application.stage))
                .where(Application.status == ApplicationStatus.active)
                .order_by(Application.priority.desc(), Application.updated_at.desc())
            )
        )
        apps_by_stage: dict[int, list[Application]] = {sid: [] for sid in stage_ids}
        for a in apps:
            apps_by_stage.setdefault(a.stage_id, []).append(a)

        cols = st.columns(len(stages))
        for idx, s in enumerate(stages):
            with cols[idx]:
                st.markdown(f"### {s.name}")
                stage_apps = apps_by_stage.get(s.id, [])
                if not stage_apps:
                    st.caption("—")
                for a in stage_apps:
                    with st.container(border=True):
                        st.write(f"**{a.job.title if a.job else 'Job'}**")
                        st.caption(a.job.company.name if a.job and a.job.company else "")
                        move_to = st.selectbox(
                            "Move to",
                            stage_ids,
                            index=stage_ids.index(s.id),
                            format_func=lambda sid: stage_name.get(sid, str(sid)),
                            key=f"move_{a.id}",
                        )
                        if move_to != s.id:
                            if st.button("Apply move", key=f"apply_move_{a.id}", type="primary", use_container_width=True):
                                set_application_stage(db, a.id, move_to)
                                db.commit()
                                st.success("Moved.")
                                st.rerun()


def page_tasks_calendar() -> None:
    st.subheader("Tasks & Calendar")
    with session_scope() as db:
        ensure_default_stages(db)
        ensure_demo_data(db, owner_user_id=current_user_id() or 1, is_admin=current_user_is_admin())
        tasks = list(
            db.scalars(
                select(Task)
                .options(joinedload(Task.application).joinedload(Application.job).joinedload(Job.company))
                .order_by(Task.due_at.asc().nulls_last(), Task.created_at.desc())
            )
        )
        followups = list(
            db.scalars(_scope_applications_query().options(joinedload(Application.job).joinedload(Job.company)).where(Application.next_follow_up_at.is_not(None)).order_by(Application.next_follow_up_at.asc()))
        )
        st.markdown("### Filters")
        only_open = st.checkbox("Only open", value=True)
        horizon_days = st.slider("Horizon (days)", 1, 60, 14)
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=horizon_days)
        selected_date = st.date_input("Selected date", value=now.date())

        filtered = []
        for t in tasks:
            if only_open and t.status != TaskStatus.open:
                continue
            due = _as_utc_aware(t.due_at)
            if due and due > cutoff:
                continue
            filtered.append(t)

        st.markdown("### Add an important event")
        with st.form("add_event", clear_on_submit=True):
            title = st.text_input("Event title", placeholder="Interview / Follow-up / Deadline")
            when = st.date_input("Event date", value=selected_date, key="event_date")
            notes = st.text_area("Details (optional)", height=80)
            important = st.checkbox("Mark as important", value=True)
            submitted = st.form_submit_button("Add event", type="primary")
            if submitted:
                if not title.strip():
                    st.error("Title is required.")
                else:
                    due_at = datetime(when.year, when.month, when.day, 9, 0, tzinfo=timezone.utc)
                    # event without application linkage: attach to a lightweight placeholder application not supported,
                    # so we store events under the oldest application if exists; otherwise ask user to create an application first.
                    any_app = db.scalar(select(Application.id).order_by(Application.created_at.asc()))
                    if not any_app:
                        st.error("Create at least one application first (events are stored under an application).")
                    else:
                        t = create_task(
                            db,
                            application_id=int(any_app),
                            title=title.strip(),
                            description=notes or None,
                            due_at=due_at,
                            remind_at=None,
                            is_recurring=False,
                            recurring_rule=None,
                        )
                        t.kind = TaskKind.event
                        t.is_important = bool(important)
                        db.commit()
                        st.success("Event added.")
                        st.rerun()

        st.markdown("### Items on selected date")
        day_rows = []
        for t in filtered:
            due = _as_utc_aware(t.due_at)
            if not due:
                continue
            if due.date() != selected_date:
                continue
            company = t.application.job.company.name if t.application and t.application.job and t.application.job.company else ""
            job_title = t.application.job.title if t.application and t.application.job else ""
            day_rows.append(
                {
                    "type": "event" if (t.kind == TaskKind.event) else "task",
                    "important": t.is_important,
                    "title": t.title,
                    "company": company,
                    "job": job_title,
                    "due_at": due,
                }
            )
        for a in followups:
            follow = _as_utc_aware(a.next_follow_up_at)
            if not follow:
                continue
            if follow.date() != selected_date:
                continue
            day_rows.append(
                {
                    "type": "follow-up",
                    "important": True,
                    "title": f"Follow up: {a.job.title if a.job else ''}",
                    "company": a.job.company.name if a.job and a.job.company else "",
                    "job": a.job.title if a.job else "",
                    "due_at": follow,
                }
            )
        if day_rows:
            st.dataframe(pd.DataFrame(day_rows).sort_values("due_at"), use_container_width=True, hide_index=True)
        else:
            st.caption("No tasks/events/follow-ups on this date.")

        st.markdown("### Upcoming list")
        rows = []
        for t in filtered:
            company = t.application.job.company.name if t.application and t.application.job and t.application.job.company else ""
            title = t.application.job.title if t.application and t.application.job else ""
            due = _as_utc_aware(t.due_at)
            remind = _as_utc_aware(t.remind_at)
            rows.append(
                {
                    "id": t.id,
                    "task": t.title,
                    "kind": t.kind.value if hasattr(t.kind, "value") else str(t.kind),
                    "important": t.is_important,
                    "status": t.status.value if hasattr(t.status, "value") else str(t.status),
                    "due_at": due,
                    "remind_at": remind,
                    "company": company,
                    "job": title,
                    "application_id": t.application_id,
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.markdown("### Calendar-style view")
        if not rows:
            st.info("No tasks in this range.")
            return
        cal = pd.DataFrame(rows)
        cal["due_date"] = pd.to_datetime(cal["due_at"]).dt.date
        by_day = cal.groupby("due_date")[["task", "important", "kind"]].apply(lambda x: list(zip(x["task"], x["kind"], x["important"]))).reset_index(name="items")
        for _, r in by_day.iterrows():
            st.markdown(f"**{r['due_date']}**")
            for task_title, kind, important in r["items"]:
                prefix = "⭐ " if important else ""
                st.write(f"- {prefix}{task_title} ({kind})")


def page_import_export() -> None:
    st.subheader("Import / Export")
    with session_scope() as db:
        ensure_demo_data(db, owner_user_id=current_user_id() or 1, is_admin=current_user_is_admin())
        st.markdown("### Export")
        st.write("Use the CLI to export all tables:")
        st.code("python -m job_tracker export --out-dir exports --json", language="bash")

        st.markdown("### Import applications (CSV)")
        st.caption("Template columns: company_name, job_title, stage, applied_on, source, priority")
        up = st.file_uploader("Upload CSV", type=["csv"])
        if up:
            df = pd.read_csv(up)
            st.dataframe(df.head(50), use_container_width=True)
            if st.button("Import", type="primary"):
                ensure_default_stages(db)
                stages = {s.name.lower(): s.id for s in db.scalars(select(Stage))}
                imported = 0
                for _, row in df.iterrows():
                    company_name = str(row.get("company_name") or "").strip()
                    job_title = str(row.get("job_title") or "").strip()
                    stage_name = str(row.get("stage") or "Applied").strip().lower()
                    if not company_name or not job_title:
                        continue
                    scoped_companies = _scope_company_query().where(Company.name == company_name)
                    company = db.scalar(scoped_companies)
                    if not company:
                        company = create_company(db, company_name, owner_user_id=current_user_id())
                    job = db.scalar(_scope_jobs_query().where(Job.company_id == company.id, Job.title == job_title))
                    if not job:
                        job = create_job(db, company.id, job_title)
                    stage_id = stages.get(stage_name) or stages.get("applied") or next(iter(stages.values()))
                    applied_on = None
                    if row.get("applied_on"):
                        try:
                            applied_on = pd.to_datetime(row["applied_on"]).date()
                        except Exception:
                            applied_on = None
                    source = str(row.get("source") or "").strip() or None
                    priority = int(row.get("priority") or 0)
                    create_application(
                        db,
                        job_id=job.id,
                        stage_id=stage_id,
                        source=source,
                        applied_on=applied_on,
                        priority=priority,
                    )
                    imported += 1
                st.success(f"Imported {imported} applications.")
                st.rerun()


def page_analytics() -> None:
    st.subheader("Analytics")
    with session_scope() as db:
        apps = pd.read_sql(select(Application), ENGINE)
        stages = pd.read_sql(select(Stage), ENGINE)
        from job_tracker.models import ApplicationStageEvent  # local import to avoid circular UI import

        events = pd.read_sql(
            select(
                ApplicationStageEvent.application_id,
                ApplicationStageEvent.from_stage_id,
                ApplicationStageEvent.to_stage_id,
                ApplicationStageEvent.changed_at,
            ),
            ENGINE,
        )
        if apps.empty:
            st.info("No data yet.")
            return
        apps["created_at"] = pd.to_datetime(apps["created_at"], errors="coerce")
        apps["week"] = apps["created_at"].dt.to_period("W").astype(str)

        st.markdown("### Applications per week")
        by_week = apps.groupby("week")["id"].count().reset_index().rename(columns={"id": "applications"})
        fig = px.bar(by_week, x="week", y="applications")
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("### Status breakdown")
        by_status = apps.groupby("status")["id"].count().reset_index().rename(columns={"id": "count"})
        st.plotly_chart(px.pie(by_status, names="status", values="count"), use_container_width=True)

        st.markdown("### Response rate")
        # "Responded" = reached Screen or beyond (by stage position), within 30 days
        s = stages[["id", "name", "position"]].copy()
        current = apps.merge(s, left_on="stage_id", right_on="id", suffixes=("", "_stage"))
        responded = current[current["position"] >= 20]
        response_rate = (len(responded) / len(current)) * 100 if len(current) else 0.0
        st.metric("Response rate (stage ≥ Screen)", f"{response_rate:.1f}%")

        st.markdown("### Stage drop-offs (current funnel)")
        funnel = (
            current.groupby(["position", "name"])["id"]
            .count()
            .reset_index()
            .sort_values(["position", "name"])
            .rename(columns={"id": "count"})
        )
        st.plotly_chart(px.bar(funnel, x="name", y="count"), use_container_width=True)

        st.markdown("### Time-to-offer")
        if events.empty:
            st.info("No stage history yet (move cards in Kanban to generate it).")
            return

        events["changed_at"] = pd.to_datetime(events["changed_at"], errors="coerce")
        events = events.merge(s.add_prefix("to_"), left_on="to_stage_id", right_on="to_id", how="left")
        offer_stage_ids = set(stages[stages["name"].str.lower() == "offer"]["id"].tolist())
        if not offer_stage_ids:
            st.info("No 'Offer' stage found.")
            return

        first_offer = events[events["to_stage_id"].isin(offer_stage_ids)].sort_values("changed_at").groupby("application_id").first().reset_index()
        if first_offer.empty:
            st.info("No offers yet.")
            return

        base = apps[["id", "applied_on", "created_at"]].copy()
        base["applied_on"] = pd.to_datetime(base["applied_on"], errors="coerce")
        base["start_at"] = base["applied_on"].fillna(base["created_at"])
        merged = first_offer.merge(base, left_on="application_id", right_on="id")
        merged["days_to_offer"] = (merged["changed_at"] - merged["start_at"]).dt.total_seconds() / 86400.0
        merged = merged[merged["days_to_offer"].notna() & (merged["days_to_offer"] >= 0)]

        if merged.empty:
            st.info("Not enough data to compute time-to-offer.")
            return

        st.metric("Median days to Offer", f"{merged['days_to_offer'].median():.1f}")
        st.plotly_chart(px.histogram(merged, x="days_to_offer", nbins=20), use_container_width=True)


def page_settings() -> None:
    st.subheader("Settings")
    st.markdown("### Email reminders")
    st.write(
        {
            "SMTP_HOST": settings.smtp_host,
            "SMTP_PORT": settings.smtp_port,
            "SMTP_USERNAME": settings.smtp_username,
            "SMTP_FROM": settings.smtp_from,
            "REMINDER_TO": str(settings.reminder_to) if settings.reminder_to else None,
        }
    )
    st.info("To send reminders, configure SMTP in `.env` then run: `python -m job_tracker send-reminders`")
    if current_user_is_admin():
        st.markdown("### Admin: create user")
        with st.form("create_user_form", clear_on_submit=True):
            username = st.text_input("New username")
            password = st.text_input("New password", type="password")
            is_admin_new = st.checkbox("Grant admin role", value=False)
            submitted = st.form_submit_button("Create user", type="primary")
            if submitted:
                if not username.strip() or not password:
                    st.error("Username and password are required.")
                else:
                    with session_scope() as db:
                        create_user(db, username=username.strip(), password=password, is_admin=is_admin_new)
                    st.success("User created.")


def run_app() -> None:
    _app_header()
    require_auth()
    page = _nav()
    if page == "Dashboard":
        page_dashboard()
    elif page == "Kanban Pipeline":
        page_kanban()
    elif page == "Applications":
        page_applications()
    elif page == "Tasks & Calendar":
        page_tasks_calendar()
    elif page == "Companies":
        page_companies()
    elif page == "Jobs":
        page_jobs()
    elif page == "Contacts":
        page_contacts()
    elif page == "Import/Export":
        page_import_export()
    elif page == "Analytics":
        page_analytics()
    elif page == "Settings":
        page_settings()

