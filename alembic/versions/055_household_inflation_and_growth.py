"""HouseholdFinance inflation_pct + contribution_growth_pct.

Revision ID: 055
Revises: 054
Create Date: 2026-04-23

Twee jaarlijkse groei-parameters die in scenario-projecties de budget-
categorieën (excl. hypotheek) en de persoons-bijdragen elk jaar laten
groeien. Gelden voor ALLE scenarios van de user.
"""
from alembic import op
import sqlalchemy as sa


revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("household_finance")}
    if "inflation_pct" not in cols:
        op.add_column(
            "household_finance",
            sa.Column(
                "inflation_pct", sa.Numeric(5, 4),
                nullable=False, server_default=sa.text("0.0250"),
            ),
        )
    if "contribution_growth_pct" not in cols:
        op.add_column(
            "household_finance",
            sa.Column(
                "contribution_growth_pct", sa.Numeric(5, 4),
                nullable=False, server_default=sa.text("0.0300"),
            ),
        )


def downgrade():
    op.drop_column("household_finance", "contribution_growth_pct")
    op.drop_column("household_finance", "inflation_pct")
