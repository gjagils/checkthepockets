"""Freeze yearly wealth plans per person.

Revision ID: 064
Revises: 063
"""
from alembic import op
import sqlalchemy as sa


revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "wealth_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("captured_automatically", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("user_id", "year", name="uq_wealth_plan_user_year"),
    )
    op.create_index("ix_wealth_plans_user_id", "wealth_plans", ["user_id"])
    op.create_table(
        "wealth_plan_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("wealth_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", sa.Integer(), sa.ForeignKey("persons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("portfolio_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("savings_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.UniqueConstraint("plan_id", "person_id", "month", name="uq_wealth_plan_entry_month"),
    )
    op.create_index("ix_wealth_plan_entries_plan_id", "wealth_plan_entries", ["plan_id"])
    op.create_index("ix_wealth_plan_entries_person_id", "wealth_plan_entries", ["person_id"])


def downgrade():
    op.drop_index("ix_wealth_plan_entries_person_id", table_name="wealth_plan_entries")
    op.drop_index("ix_wealth_plan_entries_plan_id", table_name="wealth_plan_entries")
    op.drop_table("wealth_plan_entries")
    op.drop_index("ix_wealth_plans_user_id", table_name="wealth_plans")
    op.drop_table("wealth_plans")
