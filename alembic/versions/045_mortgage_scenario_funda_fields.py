"""Funda-URL en foto-URL op MortgageScenario (LIN-33).

Revision ID: 045
Revises: 044
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa


revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("mortgage_scenarios")}
    if "funda_url" not in cols:
        op.add_column(
            "mortgage_scenarios",
            sa.Column("funda_url", sa.String(500), nullable=True),
        )
    if "photo_url" not in cols:
        op.add_column(
            "mortgage_scenarios",
            sa.Column("photo_url", sa.String(500), nullable=True),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("mortgage_scenarios")}
    for name in ("photo_url", "funda_url"):
        if name in cols:
            try:
                op.drop_column("mortgage_scenarios", name)
            except Exception:
                pass
