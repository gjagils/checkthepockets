"""Add original_date to transactions for period-shift bookkeeping.

Revision ID: 030
Revises: 029
"""

from alembic import op
import sqlalchemy as sa

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("transactions", sa.Column("original_date", sa.Date(), nullable=True))


def downgrade():
    op.drop_column("transactions", "original_date")
