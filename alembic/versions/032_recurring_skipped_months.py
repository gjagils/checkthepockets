"""Add skipped_months to recurring_transactions — markeer een maand als 'niet verwacht dit jaar'.

Revision ID: 032
Revises: 031
"""

from alembic import op
import sqlalchemy as sa

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "recurring_transactions",
        sa.Column("skipped_months", sa.String(length=2000), nullable=True),
    )


def downgrade():
    op.drop_column("recurring_transactions", "skipped_months")
