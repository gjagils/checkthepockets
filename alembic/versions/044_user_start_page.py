"""Per-user startpagina-voorkeur.

Revision ID: 044
Revises: 043
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa


revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "start_page" not in cols:
        op.add_column(
            "users",
            sa.Column(
                "start_page", sa.String(100), nullable=True, server_default="/dashboard",
            ),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "start_page" in cols:
        try:
            op.drop_column("users", "start_page")
        except Exception:
            pass
