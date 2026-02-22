"""Add account_id to categories and update unique constraint

Revision ID: 004
Revises: 003
Create Date: 2026-02-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add account_id column
    op.add_column(
        "categories",
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
    )

    # Drop old unique constraint and add new one with account_id
    op.drop_constraint("uq_user_category", "categories", type_="unique")
    op.create_unique_constraint(
        "uq_user_account_category", "categories", ["user_id", "account_id", "name"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_user_account_category", "categories", type_="unique")
    op.create_unique_constraint(
        "uq_user_category", "categories", ["user_id", "name"]
    )
    op.drop_column("categories", "account_id")
