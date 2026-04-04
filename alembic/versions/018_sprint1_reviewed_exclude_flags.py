"""Add is_reviewed to transactions, exclude_from_budget and exclude_from_totals to categories

Revision ID: 018
Revises: 017
Create Date: 2026-04-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("is_reviewed", sa.Integer(), server_default="0", nullable=False))
    op.add_column("categories", sa.Column("exclude_from_budget", sa.Integer(), server_default="0", nullable=False))
    op.add_column("categories", sa.Column("exclude_from_totals", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("transactions", "is_reviewed")
    op.drop_column("categories", "exclude_from_budget")
    op.drop_column("categories", "exclude_from_totals")
