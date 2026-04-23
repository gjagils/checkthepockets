"""HRA fiscal refinements: correction factor, EWF%, WOZ, HRA end date.

Revision ID: 053
Revises: 052
Create Date: 2026-04-23

Voegt de velden toe die nodig zijn voor een realistischere
hypotheekrenteaftrek-berekening:

* HouseholdFinance.hra_correction_factor — kalibratie van modelmatige teruggaaf
  vs. werkelijke aangifte (default 1.0, geen correctie).
* HouseholdFinance.ewf_pct — eigenwoningforfait-percentage (default 0.35%).
* MortgageScenario.woz_value — WOZ-waarde (fallback = valuation).
* ScenarioExistingMortgage.hra_end_date — einddatum HRA voor dit leningdeel
  (Wet IB 2001 30-jaars-termijn; leeg = altijd aftrekbaar).
"""
from alembic import op
import sqlalchemy as sa


revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    hh_cols = {c["name"] for c in inspector.get_columns("household_finance")}
    if "hra_correction_factor" not in hh_cols:
        op.add_column(
            "household_finance",
            sa.Column(
                "hra_correction_factor", sa.Numeric(5, 4),
                nullable=False, server_default=sa.text("1.0000"),
            ),
        )
    if "ewf_pct" not in hh_cols:
        op.add_column(
            "household_finance",
            sa.Column(
                "ewf_pct", sa.Numeric(6, 4),
                nullable=False, server_default=sa.text("0.0035"),
            ),
        )

    scen_cols = {c["name"] for c in inspector.get_columns("mortgage_scenarios")}
    if "woz_value" not in scen_cols:
        op.add_column(
            "mortgage_scenarios",
            sa.Column("woz_value", sa.Numeric(12, 2), nullable=True),
        )

    em_cols = {c["name"] for c in inspector.get_columns("scenario_existing_mortgages")}
    if "hra_end_date" not in em_cols:
        op.add_column(
            "scenario_existing_mortgages",
            sa.Column("hra_end_date", sa.Date(), nullable=True),
        )


def downgrade():
    op.drop_column("scenario_existing_mortgages", "hra_end_date")
    op.drop_column("mortgage_scenarios", "woz_value")
    op.drop_column("household_finance", "ewf_pct")
    op.drop_column("household_finance", "hra_correction_factor")
