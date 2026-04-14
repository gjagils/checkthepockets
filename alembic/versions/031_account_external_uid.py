"""Add external_uid to accounts for reliable matching across bank syncs.

Revision ID: 031
Revises: 030
"""

from alembic import op
import sqlalchemy as sa

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("accounts", sa.Column("external_uid", sa.String(length=255), nullable=True))
    op.create_index("ix_accounts_external_uid", "accounts", ["external_uid"])


def downgrade():
    op.drop_index("ix_accounts_external_uid", table_name="accounts")
    op.drop_column("accounts", "external_uid")
