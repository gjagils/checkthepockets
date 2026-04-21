"""Geboortedatum op Person (LIN-34).

Revision ID: 046
Revises: 045
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa


revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("persons")}
    if "birthdate" not in cols:
        op.add_column(
            "persons",
            sa.Column("birthdate", sa.Date(), nullable=True),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("persons")}
    if "birthdate" in cols:
        try:
            op.drop_column("persons", "birthdate")
        except Exception:
            pass
