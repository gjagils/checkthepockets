"""Add weekly digest preferences to users.

Revision ID: 035
Revises: 034
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa


revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("users")}

    if "weekly_digest_enabled" not in existing:
        op.add_column(
            "users",
            sa.Column("weekly_digest_enabled", sa.Integer(), nullable=False, server_default="0"),
        )
    if "weekly_digest_weekday" not in existing:
        op.add_column(
            "users",
            sa.Column("weekly_digest_weekday", sa.Integer(), nullable=False, server_default="4"),
        )
    if "weekly_digest_hour" not in existing:
        op.add_column(
            "users",
            sa.Column("weekly_digest_hour", sa.Integer(), nullable=False, server_default="8"),
        )
    if "weekly_digest_last_sent_at" not in existing:
        op.add_column(
            "users",
            sa.Column("weekly_digest_last_sent_at", sa.DateTime(), nullable=True),
        )


def downgrade():
    for col in (
        "weekly_digest_last_sent_at",
        "weekly_digest_hour",
        "weekly_digest_weekday",
        "weekly_digest_enabled",
    ):
        try:
            op.drop_column("users", col)
        except Exception:
            pass
