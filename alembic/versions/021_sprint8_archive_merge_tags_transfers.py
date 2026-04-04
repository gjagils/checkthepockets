"""Sprint 8: category/tag archive, tag colors, transfer transactions

Revision ID: 021
Revises: 020
Create Date: 2026-04-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("categories", sa.Column("is_archived", sa.Integer(), server_default="0", nullable=False))
    op.add_column("tags", sa.Column("color", sa.String(7), nullable=True))
    op.add_column("tags", sa.Column("is_archived", sa.Integer(), server_default="0", nullable=False))
    op.add_column(
        "transactions",
        sa.Column(
            "transfer_id",
            sa.Integer(),
            sa.ForeignKey("transactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("transactions", "transfer_id")
    op.drop_column("tags", "is_archived")
    op.drop_column("tags", "color")
    op.drop_column("categories", "is_archived")
