"""Sprint 5: rule extensions — rename counterparty, set reviewed, account condition

Revision ID: 023
Revises: 022
Create Date: 2026-04-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rules",
        sa.Column("action_rename_counterparty", sa.String(255), nullable=True),
    )
    op.add_column(
        "rules",
        sa.Column("action_set_reviewed", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "rules",
        sa.Column(
            "condition_account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("rules", "action_rename_counterparty")
    op.drop_column("rules", "action_set_reviewed")
    op.drop_column("rules", "condition_account_id")
