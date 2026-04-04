"""Add start_date/end_date to recurring_transactions and recurring_id to transactions

Revision ID: 020
Revises: 019
Create Date: 2026-04-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("recurring_transactions", sa.Column("start_date", sa.Date(), nullable=True))
    op.add_column("recurring_transactions", sa.Column("end_date", sa.Date(), nullable=True))
    op.add_column(
        "transactions",
        sa.Column(
            "recurring_id",
            sa.Integer(),
            sa.ForeignKey("recurring_transactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("transactions", "recurring_id")
    op.drop_column("recurring_transactions", "end_date")
    op.drop_column("recurring_transactions", "start_date")
