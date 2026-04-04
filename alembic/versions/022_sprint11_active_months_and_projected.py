"""Sprint 11 + 10: active_months on recurring, is_projected on transactions

Revision ID: 022
Revises: 021
Create Date: 2026-04-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "recurring_transactions",
        sa.Column("active_months", sa.String(50), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("is_projected", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("recurring_transactions", "active_months")
    op.drop_column("transactions", "is_projected")
