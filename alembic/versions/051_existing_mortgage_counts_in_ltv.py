"""Vlag 'counts_in_ltv' op bestaande hypotheek per scenario.

Onderscheid tussen bank-hypotheken (tellen mee in LTV) en privé-leningen
(tellen wel mee als dekking, maar niet in de LTV-berekening die de bank
gebruikt). Default 1 zodat bestaande rijen het oude gedrag behouden.

Revision ID: 051
Revises: 050
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa


revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("scenario_existing_mortgages")}
    if "counts_in_ltv" not in cols:
        op.add_column(
            "scenario_existing_mortgages",
            sa.Column(
                "counts_in_ltv",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("scenario_existing_mortgages")}
    if "counts_in_ltv" in cols:
        try:
            op.drop_column("scenario_existing_mortgages", "counts_in_ltv")
        except Exception:
            pass
