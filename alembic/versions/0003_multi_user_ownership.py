"""Add multi-user ownership and admin flag.

Revision ID: 0003_multi_user_ownership
Revises: 0002_users_and_calendar_events
Create Date: 2026-04-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_multi_user_ownership"
down_revision = "0002_users_and_calendar_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    user_cols = {c["name"] for c in inspector.get_columns("users")}
    company_cols = {c["name"] for c in inspector.get_columns("companies")}
    contact_cols = {c["name"] for c in inspector.get_columns("contacts")}

    if "is_admin" not in user_cols:
        op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    if "owner_user_id" not in company_cols:
        op.add_column("companies", sa.Column("owner_user_id", sa.Integer(), nullable=True))
    if "owner_user_id" not in contact_cols:
        op.add_column("contacts", sa.Column("owner_user_id", sa.Integer(), nullable=True))

    # SQLite cannot ALTER TABLE to add FKs without batch mode; keep logical ownership via indexed columns.
    existing_indexes_companies = {i["name"] for i in inspector.get_indexes("companies")}
    existing_indexes_contacts = {i["name"] for i in inspector.get_indexes("contacts")}
    if "ix_companies_owner_user_id" not in existing_indexes_companies:
        op.create_index("ix_companies_owner_user_id", "companies", ["owner_user_id"], unique=False)
    if "ix_contacts_owner_user_id" not in existing_indexes_contacts:
        op.create_index("ix_contacts_owner_user_id", "contacts", ["owner_user_id"], unique=False)

    # migrate existing global data to first user (admin)
    op.execute("UPDATE users SET is_admin = 1 WHERE id = (SELECT id FROM users ORDER BY id LIMIT 1)")
    op.execute(
        "UPDATE companies SET owner_user_id = (SELECT id FROM users ORDER BY id LIMIT 1) "
        "WHERE owner_user_id IS NULL"
    )
    op.execute(
        "UPDATE contacts SET owner_user_id = (SELECT id FROM users ORDER BY id LIMIT 1) "
        "WHERE owner_user_id IS NULL"
    )

    # old global uniqueness -> per-owner uniqueness
    if "ix_companies_name" in existing_indexes_companies:
        op.drop_index("ix_companies_name", table_name="companies")
    op.create_index("ix_companies_name", "companies", ["name"], unique=False)
    # SQLite can't add unique constraints post-hoc reliably without batch mode;
    # app-level checks still prevent duplicates per user.


def downgrade() -> None:
    op.drop_constraint("uq_companies_owner_name", "companies", type_="unique")
    op.drop_index("ix_companies_name", table_name="companies")
    op.create_index("ix_companies_name", "companies", ["name"], unique=True)
    op.drop_index("ix_contacts_owner_user_id", table_name="contacts")
    op.drop_index("ix_companies_owner_user_id", table_name="companies")
    op.drop_column("contacts", "owner_user_id")
    op.drop_column("companies", "owner_user_id")
    op.drop_column("users", "is_admin")

