"""rule_suggestions table for AI-analyzed transaction patterns

Revision ID: 027
"""

import sqlalchemy as sa
from alembic import op

revision = "027"
down_revision = "026"


def upgrade():
    op.create_table(
        "rule_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("match_value", sa.String(255), nullable=False),
        sa.Column("match_field", sa.String(20), nullable=False, server_default="description"),
        sa.Column("counterparty_clean", sa.String(255), nullable=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("category_name", sa.String(100), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("uncat_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cat_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("rule_suggestions")
