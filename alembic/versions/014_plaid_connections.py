"""Add plaid_connections table for bank API integrations

Revision ID: 014
Revises: 013
Create Date: 2026-02-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plaid_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("institution_id", sa.String(100), nullable=True),
        sa.Column("institution_name", sa.String(255), nullable=False),
        sa.Column("access_token", sa.String(255), nullable=False),
        sa.Column("item_id", sa.String(100), nullable=False),
        sa.Column("plaid_account_id", sa.String(100), nullable=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), server_default="active"),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("plaid_connections")
