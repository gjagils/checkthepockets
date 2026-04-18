"""Hypotheek-fundering: household_finance, mortgage_rate_table, mortgage_scenarios, mortgage_variants.

Revision ID: 042
Revises: 041
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa


revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "household_finance" not in tables:
        op.create_table(
            "household_finance",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
            ),
            sa.Column("salary_primary", sa.Numeric(12, 2), server_default="0"),
            sa.Column("salary_primary_name", sa.String(100), nullable=True),
            sa.Column("salary_secondary", sa.Numeric(12, 2), server_default="0"),
            sa.Column("salary_secondary_name", sa.String(100), nullable=True),
            sa.Column("existing_mortgage_pim", sa.Numeric(12, 2), server_default="0"),
            sa.Column("existing_mortgage_interest_only", sa.Numeric(12, 2), server_default="0"),
            sa.Column("existing_mortgage_interest_only_monthly", sa.Numeric(12, 2), server_default="0"),
            sa.Column("existing_mortgage_pim_rate", sa.Numeric(6, 4), server_default="0"),
            sa.Column("existing_mortgage_pim_refund_rate", sa.Numeric(6, 4), server_default="0"),
            sa.Column("current_home_debt", sa.Numeric(12, 2), server_default="0"),
            sa.Column("tax_rate", sa.Numeric(6, 4), server_default="0.3697"),
            sa.Column("notional_rent_value", sa.Numeric(12, 2), server_default="3600"),
            sa.Column("purchase_costs_pct", sa.Numeric(6, 4), server_default="0.025"),
            sa.Column("selling_costs_pct", sa.Numeric(6, 4), server_default="0.015"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        )

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "mortgage_rate_table" not in tables:
        op.create_table(
            "mortgage_rate_table",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("fixed_years", sa.Integer(), nullable=False),
            sa.Column("ltv_max_pct", sa.Numeric(6, 4), nullable=False),
            sa.Column("interest_rate", sa.Numeric(6, 4), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.UniqueConstraint(
                "user_id", "fixed_years", "ltv_max_pct", name="uq_rate_user_fixed_ltv",
            ),
        )

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "mortgage_scenarios" not in tables:
        op.create_table(
            "mortgage_scenarios",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(150), nullable=False),
            sa.Column("valuation", sa.Numeric(12, 2), server_default="0"),
            sa.Column("offer", sa.Numeric(12, 2), server_default="0"),
            sa.Column("renovation_cost", sa.Numeric(12, 2), server_default="0"),
            sa.Column("own_contribution", sa.Numeric(12, 2), server_default="0"),
            sa.Column("sale_old_home", sa.Numeric(12, 2), server_default="0"),
            sa.Column("energy_label", sa.String(2), server_default="A"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("is_archived", sa.Integer(), server_default="0"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        )

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "mortgage_variants" not in tables:
        op.create_table(
            "mortgage_variants",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "scenario_id",
                sa.Integer(),
                sa.ForeignKey("mortgage_scenarios.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("fixed_years", sa.Integer(), nullable=False),
            sa.Column("interest_rate_override", sa.Numeric(6, 4), nullable=True),
            sa.UniqueConstraint(
                "scenario_id", "fixed_years", name="uq_variant_scenario_fixed",
            ),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    for tbl in ("mortgage_variants", "mortgage_scenarios", "mortgage_rate_table", "household_finance"):
        if tbl in tables:
            try:
                op.drop_table(tbl)
            except Exception:
                pass
