"""Add account_id to recurring_transactions with best-effort backfill.

Revision ID: 041
Revises: 040
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa


revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("recurring_transactions")}

    if "account_id" not in existing:
        op.add_column(
            "recurring_transactions",
            sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        )

    # Best-effort backfill: voor elke recurring, neem de meest voorkomende
    # account_id van gelinkte transacties (Transaction.recurring_id -> rec.id).
    # Geen match? account_id blijft NULL.
    bind.execute(
        sa.text(
            """
            UPDATE recurring_transactions
            SET account_id = (
                SELECT t.account_id
                FROM transactions t
                WHERE t.recurring_id = recurring_transactions.id
                  AND t.account_id IS NOT NULL
                GROUP BY t.account_id
                ORDER BY COUNT(*) DESC, t.account_id ASC
                LIMIT 1
            )
            WHERE account_id IS NULL
            """
        )
    )


def downgrade():
    try:
        op.drop_column("recurring_transactions", "account_id")
    except Exception:
        pass
