"""Add portfolio assets, persons, and holdings tables

Revision ID: 012
Revises: 011
Create Date: 2026-02-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "portfolio_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("asset_class", sa.String(20), nullable=False),
        sa.Column("unit", sa.String(20), server_default="oz"),
        sa.Column("current_price_eur", sa.Numeric(16, 4), server_default="0"),
        sa.Column("price_updated_at", sa.DateTime(), nullable=True),
        sa.Column("monthly_growth_pct", sa.Numeric(6, 2), server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "portfolio_persons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "portfolio_holdings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("portfolio_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", sa.Integer(), sa.ForeignKey("portfolio_persons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quantity", sa.Numeric(16, 8), server_default="0"),
        sa.UniqueConstraint("user_id", "asset_id", "person_id", name="uq_holding_user_asset_person"),
    )


def downgrade() -> None:
    op.drop_table("portfolio_holdings")
    op.drop_table("portfolio_persons")
    op.drop_table("portfolio_assets")
