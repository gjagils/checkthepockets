"""Add one-off monthly wealth adjustments.

Revision ID: 065
Revises: 064
"""
from alembic import op
import sqlalchemy as sa

revision = "065"
down_revision = "064"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "wealth_adjustments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("portfolio_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", sa.Integer(), sa.ForeignKey("persons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.UniqueConstraint("user_id", "asset_id", "person_id", "year", "month", name="uq_wealth_adjustment_month"),
    )
    op.create_index("ix_wealth_adjustments_user_id", "wealth_adjustments", ["user_id"])


def downgrade():
    op.drop_index("ix_wealth_adjustments_user_id", table_name="wealth_adjustments")
    op.drop_table("wealth_adjustments")
