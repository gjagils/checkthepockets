"""Add is_income to savings_lines

Revision ID: 005
Revises: 004
Create Date: 2026-02-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "savings_lines",
        sa.Column("is_income", sa.Integer(), server_default="0", nullable=False),
    )

    # Back-fill from linked category where possible
    op.execute("""
        UPDATE savings_lines
        SET is_income = (
            SELECT categories.is_income
            FROM categories
            WHERE categories.id = savings_lines.category_id
        )
        WHERE category_id IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_column("savings_lines", "is_income")
