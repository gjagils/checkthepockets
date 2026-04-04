"""Sprint 14+15: email verification, password reset, invite, admin, rate limiting

Revision ID: 024
Revises: 023
Create Date: 2026-04-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "024"
down_revision: Union[str, None] = "023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Users: new fields ---
    op.add_column("users", sa.Column("email", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("is_verified", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("users", sa.Column("is_admin", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))

    # --- auth_tokens table ---
    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("token", sa.String(128), unique=True, nullable=False),
        sa.Column("token_type", sa.String(20), nullable=False),  # verify_email | reset_password | invite
        sa.Column("email", sa.String(255), nullable=True),        # for invite tokens
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("auth_tokens")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "is_active")
    op.drop_column("users", "is_admin")
    op.drop_column("users", "is_verified")
    op.drop_column("users", "email")
