"""Add sort_order to categories

Revision ID: 007
Revises: 006
Create Date: 2026-02-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "categories",
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("categories", "sort_order")
