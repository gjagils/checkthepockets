"""bunq ids exceed 32 bits: widen bunq_account_links id columns to BIGINT.

Revision ID: 068
Revises: 067
"""
from alembic import op
import sqlalchemy as sa

revision = "068"
down_revision = "067"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("bunq_account_links", "bunq_account_id",
                    existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=False)
    op.alter_column("bunq_account_links", "last_payment_id",
                    existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=True)


def downgrade():
    op.alter_column("bunq_account_links", "last_payment_id",
                    existing_type=sa.BigInteger(), type_=sa.Integer(), existing_nullable=True)
    op.alter_column("bunq_account_links", "bunq_account_id",
                    existing_type=sa.BigInteger(), type_=sa.Integer(), existing_nullable=False)
