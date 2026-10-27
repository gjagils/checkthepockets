"""AI-categoriesuggesties per tegenpartij als cache (ACT-58).

Revision ID: 072
Revises: 071
"""
from alembic import op
import sqlalchemy as sa

revision = "072"
down_revision = "071"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "merchant_category_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("merchant_hash", sa.String(64), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "merchant_hash", name="uq_merchant_suggestion_user_hash"),
    )


def downgrade():
    op.drop_table("merchant_category_suggestions")
