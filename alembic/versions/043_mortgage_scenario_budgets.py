"""Scenario-specifieke budget-overrides per categorie.

Revision ID: 043
Revises: 042
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa


revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "mortgage_scenario_budgets" not in set(inspector.get_table_names()):
        op.create_table(
            "mortgage_scenario_budgets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "scenario_id",
                sa.Integer(),
                sa.ForeignKey("mortgage_scenarios.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "category_id",
                sa.Integer(),
                sa.ForeignKey("categories.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.UniqueConstraint(
                "scenario_id", "category_id",
                name="uq_scenario_budget_scenario_category",
            ),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "mortgage_scenario_budgets" in set(inspector.get_table_names()):
        try:
            op.drop_table("mortgage_scenario_budgets")
        except Exception:
            pass
