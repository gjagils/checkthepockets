"""Add is_excluded column to transactions for soft-delete

Revision ID: 015
Revises: 014
Create Date: 2026-02-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("is_excluded", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("transactions", "is_excluded")
