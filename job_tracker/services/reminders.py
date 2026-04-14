from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import smtplib

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from job_tracker.config import settings
from job_tracker.models import Task, TaskStatus


@dataclass(frozen=True)
class ReminderEmail:
    subject: str
    body: str


def _build_email(task: Task) -> ReminderEmail:
    due = task.due_at.isoformat() if task.due_at else "N/A"
    subject = f"Job Tracker reminder: {task.title}"
    body = "\n".join(
        [
            f"Task: {task.title}",
            f"Due: {due}",
            "",
            task.description or "",
            "",
            "This reminder was sent by your Job Tracker app.",
        ]
    ).strip()
    return ReminderEmail(subject=subject, body=body)


def _send_smtp(to_email: str, subject: str, body: str) -> None:
    if not (settings.smtp_host and settings.smtp_username and settings.smtp_password and settings.smtp_from):
        raise RuntimeError("SMTP not configured. Set SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD/SMTP_FROM in .env")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    msg.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as s:
        s.starttls()
        s.login(settings.smtp_username, settings.smtp_password)
        s.send_message(msg)


def _next_recurring_time(task: Task, base: datetime) -> datetime | None:
    if not task.is_recurring or not task.recurring_rule:
        return None
    rule = task.recurring_rule.lower().strip()
    if rule == "daily":
        return base + timedelta(days=1)
    if rule == "weekly":
        return base + timedelta(days=7)
    if rule == "monthly":
        return base + timedelta(days=30)
    return None


def send_due_task_reminders(db: Session, now: datetime | None = None, dry_run: bool = False) -> int:
    now = now or datetime.now(timezone.utc)
    to_email = (settings.reminder_to or settings.smtp_username)
    if not to_email:
        raise RuntimeError("No reminder recipient configured. Set REMINDER_TO or SMTP_USERNAME in .env")

    q = select(Task).where(
        and_(
            Task.status == TaskStatus.open,
            Task.remind_at.is_not(None),
            Task.remind_at <= now,
            or_(Task.snoozed_until.is_(None), Task.snoozed_until <= now),
        )
    )
    tasks = list(db.scalars(q))
    sent = 0
    for t in tasks:
        email = _build_email(t)
        if not dry_run:
            _send_smtp(to_email=str(to_email), subject=email.subject, body=email.body)
        sent += 1

        # Move remind_at forward to avoid spamming; recurring tasks reschedule, non-recurring clear.
        next_time = _next_recurring_time(t, base=now)
        if next_time:
            t.remind_at = next_time
            if t.due_at:
                t.due_at = _next_recurring_time(t, base=t.due_at) or t.due_at
        else:
            t.remind_at = None
    return sent

