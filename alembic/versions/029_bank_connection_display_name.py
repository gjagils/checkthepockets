"""Add display_name to bank_connections.

Revision ID: 029
Revises: 028
"""

from alembic import op
import sqlalchemy as sa

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("bank_connections", sa.Column("display_name", sa.String(100), nullable=True))


def downgrade():
    op.drop_column("bank_connections", "display_name")
