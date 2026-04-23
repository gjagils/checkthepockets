"""HouseholdFinance jaar-inkomsten + jaar-uitgaven voor spaarrekening.

Revision ID: 056
Revises: 055
Create Date: 2026-04-23

Zes nieuwe bedragen per jaar op HouseholdFinance voor het "Jaarlijks
spaarsaldo"-overzicht per scenario:

Inkomsten (vloeien naar spaarrekening):
* annual_child_benefit — kinderbijslag
* annual_private_loan_refund — rente-restitutie privélening (bv. Pa Pim)
* annual_extra_primary — vakantiegeld + 13e maand persoon 1
* annual_extra_secondary — vakantiegeld + 13e maand persoon 2

Uitgaven (komen van spaarrekening af):
* annual_vacation_budget — jaarlijks vakantiebudget
* annual_house_budget — jaarlijks huis-onderhoudsbudget
"""
from alembic import op
import sqlalchemy as sa


revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None


_NEW_COLUMNS = [
    "annual_child_benefit",
    "annual_private_loan_refund",
    "annual_extra_primary",
    "annual_extra_secondary",
    "annual_vacation_budget",
    "annual_house_budget",
]


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("household_finance")}
    for name in _NEW_COLUMNS:
        if name not in cols:
            op.add_column(
                "household_finance",
                sa.Column(
                    name, sa.Numeric(10, 2),
                    nullable=False, server_default=sa.text("0"),
                ),
            )


def downgrade():
    for name in reversed(_NEW_COLUMNS):
        op.drop_column("household_finance", name)
