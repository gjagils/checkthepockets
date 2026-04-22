"""Scenario budget factors + cost_scale_type + person contributions (LIN-45).

Revision ID: 050
Revises: 049
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa


revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    scen_cols = {c["name"] for c in inspector.get_columns("mortgage_scenarios")}
    if "municipal_cost_factor" not in scen_cols:
        op.add_column(
            "mortgage_scenarios",
            sa.Column(
                "municipal_cost_factor", sa.Numeric(4, 2),
                nullable=False, server_default=sa.text("1.5"),
            ),
        )
    if "insurance_cost_factor" not in scen_cols:
        op.add_column(
            "mortgage_scenarios",
            sa.Column(
                "insurance_cost_factor", sa.Numeric(4, 2),
                nullable=False, server_default=sa.text("1.5"),
            ),
        )

    cat_cols = {c["name"] for c in inspector.get_columns("categories")}
    if "cost_scale_type" not in cat_cols:
        op.add_column(
            "categories",
            sa.Column("cost_scale_type", sa.String(20), nullable=True),
        )

    budget_cols = {c["name"] for c in inspector.get_columns("mortgage_scenario_budgets")}
    if "source" not in budget_cols:
        op.add_column(
            "mortgage_scenario_budgets",
            sa.Column(
                "source", sa.String(10),
                nullable=False, server_default="manual",
            ),
        )

    if "scenario_person_contributions" not in inspector.get_table_names():
        op.create_table(
            "scenario_person_contributions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "scenario_id", sa.Integer(),
                sa.ForeignKey("mortgage_scenarios.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "person_id", sa.Integer(),
                sa.ForeignKey("persons.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "monthly_contribution_eur", sa.Numeric(10, 2),
                nullable=False, server_default="0",
            ),
            sa.UniqueConstraint(
                "scenario_id", "person_id",
                name="uq_scenario_person_contribution",
            ),
        )
        op.create_index(
            "ix_scenario_person_contributions_scenario_id",
            "scenario_person_contributions", ["scenario_id"],
        )
        op.create_index(
            "ix_scenario_person_contributions_person_id",
            "scenario_person_contributions", ["person_id"],
        )


def downgrade():
    try:
        op.drop_index(
            "ix_scenario_person_contributions_person_id",
            table_name="scenario_person_contributions",
        )
        op.drop_index(
            "ix_scenario_person_contributions_scenario_id",
            table_name="scenario_person_contributions",
        )
    except Exception:
        pass
    op.drop_table("scenario_person_contributions")
    op.drop_column("mortgage_scenario_budgets", "source")
    op.drop_column("categories", "cost_scale_type")
    op.drop_column("mortgage_scenarios", "insurance_cost_factor")
    op.drop_column("mortgage_scenarios", "municipal_cost_factor")
