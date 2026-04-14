"""Track which rule (if any) assigned the category of a transaction.

Revision ID: 033
Revises: 032
"""

from alembic import op
import sqlalchemy as sa

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "transactions",
        sa.Column("assigned_by_rule_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_transactions_assigned_by_rule",
        "transactions",
        "rules",
        ["assigned_by_rule_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_transactions_assigned_by_rule_id",
        "transactions",
        ["assigned_by_rule_id"],
    )


def downgrade():
    op.drop_index("ix_transactions_assigned_by_rule_id", table_name="transactions")
    op.drop_constraint("fk_transactions_assigned_by_rule", "transactions", type_="foreignkey")
    op.drop_column("transactions", "assigned_by_rule_id")
