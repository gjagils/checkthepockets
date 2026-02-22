"""Add rules table for auto-categorization

Revision ID: 003
Revises: 002
Create Date: 2026-02-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Integer(), server_default="1"),
        # IF conditions
        sa.Column("match_field", sa.String(20), nullable=False),
        sa.Column("match_type", sa.String(20), nullable=False),
        sa.Column("match_value", sa.String(255), nullable=False),
        sa.Column("amount_min", sa.Numeric(12, 2), nullable=True),
        sa.Column("amount_max", sa.Numeric(12, 2), nullable=True),
        # THEN actions
        sa.Column(
            "assign_category_id",
            sa.Integer(),
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "assign_tag_id",
            sa.Integer(),
            sa.ForeignKey("tags.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_rules_user_id", "rules", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_rules_user_id")
    op.drop_table("rules")
