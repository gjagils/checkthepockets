"""Savings planner: savings_plans, savings_lines, savings_entries

Revision ID: 003
Revises: 002
Create Date: 2026-02-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "savings_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False
        ),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("starting_balance", sa.Numeric(12, 2), server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("account_id", "year", name="uq_savings_plan_account_year"),
    )
    op.create_index(
        "ix_savings_plans_user_year", "savings_plans", ["user_id", "year"]
    )

    op.create_table(
        "savings_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("savings_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("annual_budget", sa.Numeric(12, 2), server_default="0"),
        sa.Column("frequency", sa.String(20), nullable=False, server_default="monthly"),
        sa.Column("default_amount", sa.Numeric(12, 2), server_default="0"),
        sa.Column("sort_order", sa.Integer(), server_default="0"),
    )
    op.create_index("ix_savings_lines_plan_id", "savings_lines", ["plan_id"])

    op.create_table(
        "savings_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "line_id",
            sa.Integer(),
            sa.ForeignKey("savings_lines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("status", sa.String(20), server_default="forecast"),
        sa.UniqueConstraint("line_id", "month", name="uq_savings_entry_line_month"),
    )
    op.create_index("ix_savings_entries_line_id", "savings_entries", ["line_id"])


def downgrade() -> None:
    op.drop_index("ix_savings_entries_line_id")
    op.drop_table("savings_entries")
    op.drop_index("ix_savings_lines_plan_id")
    op.drop_table("savings_lines")
    op.drop_index("ix_savings_plans_user_year")
    op.drop_table("savings_plans")
