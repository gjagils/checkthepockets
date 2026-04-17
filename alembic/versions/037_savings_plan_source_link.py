"""Add source_plan_id FK to savings_plans for year-to-year linking.

Revision ID: 037
Revises: 036
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa


revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("savings_plans")}

    if "source_plan_id" not in existing:
        op.add_column(
            "savings_plans",
            sa.Column("source_plan_id", sa.Integer(), nullable=True),
        )
        # Named FK via batch so SQLite can add it reliably
        with op.batch_alter_table("savings_plans") as batch:
            batch.create_foreign_key(
                "fk_savings_plans_source_plan_id",
                "savings_plans",
                ["source_plan_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade():
    try:
        with op.batch_alter_table("savings_plans") as batch:
            batch.drop_constraint("fk_savings_plans_source_plan_id", type_="foreignkey")
    except Exception:
        pass
    try:
        op.drop_column("savings_plans", "source_plan_id")
    except Exception:
        pass
