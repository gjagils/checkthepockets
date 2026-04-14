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
    # Drop FK column on rules first (references tags.id)
    with op.batch_alter_table("rules") as batch_op:
        try:
            batch_op.drop_constraint("fk_rules_assign_tag_id", type_="foreignkey")
        except Exception:
            pass
        batch_op.drop_column("assign_tag_id")

    # Drop association table
    op.drop_table("transaction_tags")

    # Drop tags table
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
    with op.batch_alter_table("rules") as batch_op:
        batch_op.add_column(sa.Column("assign_tag_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_rules_assign_tag_id", "tags", ["assign_tag_id"], ["id"], ondelete="SET NULL"
        )
