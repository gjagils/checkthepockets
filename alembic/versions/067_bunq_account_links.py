"""Add account kind and bunq account links.

Revision ID: 067
Revises: 066
"""
from alembic import op
import sqlalchemy as sa

revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("accounts", sa.Column("kind", sa.String(length=20), nullable=False, server_default="payment"))
    op.create_table(
        "bunq_account_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("connection_id", sa.Integer(), sa.ForeignKey("bunq_connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bunq_account_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("iban", sa.String(length=34), nullable=True),
        sa.Column("bunq_kind", sa.String(length=60), nullable=True),
        sa.Column("bunq_status", sa.String(length=30), nullable=True),
        sa.Column("balance", sa.Numeric(14, 2), nullable=True),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("last_payment_id", sa.Integer(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("connection_id", "bunq_account_id", name="uq_bunq_link_account"),
    )
    op.create_index("ix_bunq_account_links_connection_id", "bunq_account_links", ["connection_id"])


def downgrade():
    op.drop_index("ix_bunq_account_links_connection_id", table_name="bunq_account_links")
    op.drop_table("bunq_account_links")
    op.drop_column("accounts", "kind")
