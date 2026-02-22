"""Add recurring_transactions table

Revision ID: 008
Revises: 007
Create Date: 2026-02-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recurring_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("amount_expected", sa.Numeric(12, 2), nullable=False),
        sa.Column("frequency", sa.String(20), nullable=False),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("counterparty", sa.String(255), nullable=True),
        sa.Column("description_match", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Integer(), server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_recurring_transactions_user_id", "recurring_transactions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_recurring_transactions_user_id")
    op.drop_table("recurring_transactions")
