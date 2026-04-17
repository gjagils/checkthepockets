"""Add cashout fee fields to portfolio_assets.

Revision ID: 040
Revises: 039
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa


revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("portfolio_assets")}

    if "cashout_fee_fixed_eur" not in existing:
        op.add_column(
            "portfolio_assets",
            sa.Column(
                "cashout_fee_fixed_eur",
                sa.Numeric(12, 2),
                nullable=True,
                server_default="0",
            ),
        )
    if "cashout_fee_pct" not in existing:
        op.add_column(
            "portfolio_assets",
            sa.Column(
                "cashout_fee_pct",
                sa.Numeric(6, 2),
                nullable=True,
                server_default="0",
            ),
        )


def downgrade():
    for col in ("cashout_fee_fixed_eur", "cashout_fee_pct"):
        try:
            op.drop_column("portfolio_assets", col)
        except Exception:
            pass
