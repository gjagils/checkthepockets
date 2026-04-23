"""Scenario monthly_refund_usage (HRA → maandlast vs sparen).

Revision ID: 052
Revises: 051
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa


revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("mortgage_scenarios")}
    if "monthly_refund_usage" not in cols:
        op.add_column(
            "mortgage_scenarios",
            sa.Column("monthly_refund_usage", sa.Numeric(10, 2), nullable=True),
        )


def downgrade():
    op.drop_column("mortgage_scenarios", "monthly_refund_usage")
