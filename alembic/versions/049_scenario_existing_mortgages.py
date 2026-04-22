"""Add scenario_existing_mortgages + purchase_fee_pct/sale_fee_pct to scenarios.

Revision ID: 049
Revises: 048
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa


revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_cols = {c["name"] for c in inspector.get_columns("mortgage_scenarios")}
    if "purchase_fee_pct" not in existing_cols:
        op.add_column(
            "mortgage_scenarios",
            sa.Column(
                "purchase_fee_pct", sa.Numeric(5, 2),
                nullable=False, server_default=sa.text("2.5"),
            ),
        )
    if "sale_fee_pct" not in existing_cols:
        op.add_column(
            "mortgage_scenarios",
            sa.Column(
                "sale_fee_pct", sa.Numeric(5, 2),
                nullable=False, server_default=sa.text("1.5"),
            ),
        )

    if "scenario_existing_mortgages" not in inspector.get_table_names():
        op.create_table(
            "scenario_existing_mortgages",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "scenario_id", sa.Integer(),
                sa.ForeignKey("mortgage_scenarios.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("balance_eur", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column(
                "mortgage_type", sa.String(20),
                nullable=False, server_default="annuity",
            ),
            sa.Column("rate_pct", sa.Numeric(6, 3), nullable=True),
            sa.Column("months_remaining", sa.Integer(), nullable=True),
            sa.Column("monthly_payment_eur", sa.Numeric(10, 2), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index(
            "ix_scenario_existing_mortgages_scenario_id",
            "scenario_existing_mortgages", ["scenario_id"],
        )


def downgrade():
    try:
        op.drop_index(
            "ix_scenario_existing_mortgages_scenario_id",
            table_name="scenario_existing_mortgages",
        )
    except Exception:
        pass
    op.drop_table("scenario_existing_mortgages")
    op.drop_column("mortgage_scenarios", "sale_fee_pct")
    op.drop_column("mortgage_scenarios", "purchase_fee_pct")
