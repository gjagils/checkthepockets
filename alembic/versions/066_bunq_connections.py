"""Add bunq API connections (encrypted key storage).

Revision ID: 066
Revises: 065
"""
from alembic import op
import sqlalchemy as sa

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "bunq_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("api_key", sa.Text(), nullable=False),
        sa.Column("private_key_pem", sa.Text(), nullable=True),
        sa.Column("installation_token", sa.Text(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(length=20), nullable=False, server_default="never"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table("bunq_connections")
