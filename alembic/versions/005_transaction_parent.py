"""Add parent_id to transactions for split/specificeer feature

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
        "transactions",
        sa.Column(
            "parent_id",
            sa.Integer(),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_transactions_parent_id", "transactions", ["parent_id"])


def downgrade() -> None:
    op.drop_index("ix_transactions_parent_id")
    op.drop_column("transactions", "parent_id")
