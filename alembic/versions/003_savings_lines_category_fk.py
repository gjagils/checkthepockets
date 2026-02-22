"""Rename savings_lines.category to category_id FK

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
    # Drop the old string column
    op.drop_column("savings_lines", "category")
    # Add the new FK column
    op.add_column(
        "savings_lines",
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("savings_lines", "category_id")
    op.add_column(
        "savings_lines",
        sa.Column("category", sa.String(100), nullable=True),
    )
