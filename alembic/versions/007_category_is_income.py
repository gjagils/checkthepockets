"""Add is_income flag to categories

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
    op.add_column("categories", sa.Column("is_income", sa.Integer(), server_default="0"))


def downgrade() -> None:
    op.drop_column("categories", "is_income")
