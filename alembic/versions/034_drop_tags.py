"""Drop tags and transaction_tags tables; remove rules.assign_tag_id.

Revision ID: 034
Revises: 033
Create Date: 2026-04-15
"""
from alembic import op
import sqlalchemy as sa


revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Drop assign_tag_id column from rules (its FK constraint drops with it on PG)
    rules_cols = {c["name"] for c in inspector.get_columns("rules")}
    if "assign_tag_id" in rules_cols:
        # Drop any FK on assign_tag_id by its actual name (auto-generated)
        for fk in inspector.get_foreign_keys("rules"):
            if "assign_tag_id" in fk.get("constrained_columns", []) and fk.get("name"):
                op.drop_constraint(fk["name"], "rules", type_="foreignkey")
        op.drop_column("rules", "assign_tag_id")

    # Drop association table
    existing_tables = set(inspector.get_table_names())
    if "transaction_tags" in existing_tables:
        op.drop_table("transaction_tags")

    # Drop tags table
    if "tags" in existing_tables:
        op.drop_table("tags")


def downgrade():
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("color", sa.String(7), nullable=True),
        sa.Column("is_archived", sa.Integer(), default=0),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "name", name="uq_user_tag"),
    )
    op.create_table(
        "transaction_tags",
        sa.Column("transaction_id", sa.Integer(), sa.ForeignKey("transactions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    )
    op.add_column("rules", sa.Column("assign_tag_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_rules_assign_tag_id", "rules", "tags", ["assign_tag_id"], ["id"], ondelete="SET NULL"
    )
