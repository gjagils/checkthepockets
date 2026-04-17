"""Add monthly_contribution_eur to portfolio_holdings for periodic storting/onttrekking.

Revision ID: 038
Revises: 037
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa


revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("portfolio_holdings")}

    if "monthly_contribution_eur" not in existing:
        op.add_column(
            "portfolio_holdings",
            sa.Column(
                "monthly_contribution_eur",
                sa.Numeric(12, 2),
                nullable=True,
                server_default="0",
            ),
        )


def downgrade():
    try:
        op.drop_column("portfolio_holdings", "monthly_contribution_eur")
    except Exception:
        pass
