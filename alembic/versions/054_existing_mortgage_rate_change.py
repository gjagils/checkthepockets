"""Bestaande hypotheek: rentesprong (rate_pct_after + rate_change_date).

Revision ID: 054
Revises: 053
Create Date: 2026-04-23

Modeleert een rentevast-einde op een bestaand leningdeel. Voorbeeld: ABN
aflossingsvrij met rente 1,76% t/m 31-12-2030 en 4,45% vanaf 01-01-2031.
"""
from alembic import op
import sqlalchemy as sa


revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("scenario_existing_mortgages")}
    if "rate_pct_after" not in cols:
        op.add_column(
            "scenario_existing_mortgages",
            sa.Column("rate_pct_after", sa.Numeric(6, 3), nullable=True),
        )
    if "rate_change_date" not in cols:
        op.add_column(
            "scenario_existing_mortgages",
            sa.Column("rate_change_date", sa.Date(), nullable=True),
        )


def downgrade():
    op.drop_column("scenario_existing_mortgages", "rate_change_date")
    op.drop_column("scenario_existing_mortgages", "rate_pct_after")
