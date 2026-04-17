"""Add ticker and exchange columns to portfolio_assets for stock support.

Revision ID: 039
Revises: 038
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa


revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("portfolio_assets")}

    if "ticker" not in existing:
        op.add_column(
            "portfolio_assets",
            sa.Column("ticker", sa.String(length=20), nullable=True),
        )
    if "exchange" not in existing:
        op.add_column(
            "portfolio_assets",
            sa.Column("exchange", sa.String(length=50), nullable=True),
        )


def downgrade():
    for col in ("ticker", "exchange"):
        try:
            op.drop_column("portfolio_assets", col)
        except Exception:
            pass
