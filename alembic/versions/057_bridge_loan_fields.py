"""Overbruggingshypotheek: rente op HouseholdFinance + timing/bedrag per scenario.

Revision ID: 057
Revises: 056
Create Date: 2026-04-24

Nieuwe velden:
* household_finance.bridge_rate_pct — overbruggingsrente (default 4,20%, ABN variabel)
* mortgage_scenarios.transfer_date_new — overdrachtsdatum nieuwe huis
* mortgage_scenarios.sale_date_old — verkoopdatum oude huis
* mortgage_scenarios.bridge_amount_override — optioneel override-bedrag
  (NULL → valt terug op berekende overwaarde)
"""
from alembic import op
import sqlalchemy as sa


revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    hf_cols = {c["name"] for c in inspector.get_columns("household_finance")}
    if "bridge_rate_pct" not in hf_cols:
        op.add_column(
            "household_finance",
            sa.Column(
                "bridge_rate_pct", sa.Numeric(6, 4),
                nullable=False, server_default=sa.text("0.0420"),
            ),
        )

    scen_cols = {c["name"] for c in inspector.get_columns("mortgage_scenarios")}
    if "transfer_date_new" not in scen_cols:
        op.add_column(
            "mortgage_scenarios",
            sa.Column("transfer_date_new", sa.Date, nullable=True),
        )
    if "sale_date_old" not in scen_cols:
        op.add_column(
            "mortgage_scenarios",
            sa.Column("sale_date_old", sa.Date, nullable=True),
        )
    if "bridge_amount_override" not in scen_cols:
        op.add_column(
            "mortgage_scenarios",
            sa.Column("bridge_amount_override", sa.Numeric(12, 2), nullable=True),
        )


def downgrade():
    op.drop_column("mortgage_scenarios", "bridge_amount_override")
    op.drop_column("mortgage_scenarios", "sale_date_old")
    op.drop_column("mortgage_scenarios", "transfer_date_new")
    op.drop_column("household_finance", "bridge_rate_pct")
