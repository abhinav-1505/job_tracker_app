"""Add users + calendar events/importance.

Revision ID: 0002_users_and_calendar_events
Revises: 0001_initial
Create Date: 2026-04-14

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_users_and_calendar_events"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=60), nullable=False),
        sa.Column("password_salt", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.add_column("tasks", sa.Column("kind", sa.String(length=30), nullable=False, server_default="task"))
    op.add_column("tasks", sa.Column("is_important", sa.Boolean(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    op.drop_column("tasks", "is_important")
    op.drop_column("tasks", "kind")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")

