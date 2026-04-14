from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from job_tracker.config import settings
from job_tracker.db import ENGINE
from job_tracker.db_session import session_scope
from job_tracker.models import (
    Application,
    Company,
    Contact,
    Job,
    Stage,
    Task,
    User,
)
from job_tracker.repositories import (
    create_user,
    ensure_default_stages,
)
from job_tracker.services.reminders import send_due_task_reminders
from job_tracker.services.demo_data import ensure_demo_data


ROOT = Path(__file__).resolve().parents[1]


def alembic_cfg() -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    # Ensure DB_URL is visible to env.py
    os.environ.setdefault("DB_URL", settings.db_url)
    return cfg


def cmd_migrate(_: argparse.Namespace) -> None:
    cfg = alembic_cfg()
    command.upgrade(cfg, "head")
    with session_scope() as db:
        ensure_default_stages(db)


def cmd_seed(_: argparse.Namespace) -> None:
    with session_scope() as db:
        ensure_default_stages(db)
        admin = db.scalar(select(User).where(User.is_admin.is_(True)))
        if not admin:
            admin = create_user(db, username="admin", password="admin123", is_admin=True)
            db.flush()
        ensure_demo_data(db, owner_user_id=admin.id, is_admin=True)


def cmd_send_reminders(args: argparse.Namespace) -> None:
    with session_scope() as db:
        count = send_due_task_reminders(db=db, now=datetime.now(timezone.utc), dry_run=args.dry_run)
    print(f"sent={count} dry_run={args.dry_run}")


def cmd_serve_capture(args: argparse.Namespace) -> None:
    import uvicorn

    from job_tracker.api_capture import create_capture_app

    host = args.host or settings.capture_api_host
    port = int(args.port or settings.capture_api_port)
    app = create_capture_app()
    uvicorn.run(app, host=host, port=port, log_level="info")


def cmd_export(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    with session_scope() as db:
        companies = pd.read_sql(select(Company), ENGINE)
        contacts = pd.read_sql(select(Contact), ENGINE)
        jobs = pd.read_sql(select(Job), ENGINE)
        stages = pd.read_sql(select(Stage), ENGINE)
        applications = pd.read_sql(select(Application), ENGINE)
        tasks = pd.read_sql(select(Task), ENGINE)

    companies.to_csv(out_dir / "companies.csv", index=False)
    contacts.to_csv(out_dir / "contacts.csv", index=False)
    jobs.to_csv(out_dir / "jobs.csv", index=False)
    stages.to_csv(out_dir / "stages.csv", index=False)
    applications.to_csv(out_dir / "applications.csv", index=False)
    tasks.to_csv(out_dir / "tasks.csv", index=False)

    if args.json:
        payload = {
            "companies": companies.to_dict(orient="records"),
            "contacts": contacts.to_dict(orient="records"),
            "jobs": jobs.to_dict(orient="records"),
            "stages": stages.to_dict(orient="records"),
            "applications": applications.to_dict(orient="records"),
            "tasks": tasks.to_dict(orient="records"),
        }
        (out_dir / "export.json").write_text(json.dumps(payload, default=str, indent=2), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="job_tracker", description="Job Tracker CLI")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="Run migrations and ensure default stages").set_defaults(func=cmd_migrate)
    sub.add_parser("seed", help="Seed database with sample data").set_defaults(func=cmd_seed)

    r = sub.add_parser("send-reminders", help="Send due task reminders via SMTP")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(func=cmd_send_reminders)

    e = sub.add_parser("export", help="Export tables to CSV (and optional JSON)")
    e.add_argument("--out-dir", default=str(ROOT / "exports"))
    e.add_argument("--json", action="store_true")
    e.set_defaults(func=cmd_export)

    s = sub.add_parser("serve-capture", help="Run local API for Chrome extension (FastAPI)")
    s.add_argument("--host", default=None, help="Default: CAPTURE_API_HOST or 127.0.0.1")
    s.add_argument("--port", type=int, default=None, help="Default: CAPTURE_API_PORT or 8765")
    s.set_defaults(func=cmd_serve_capture)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)

