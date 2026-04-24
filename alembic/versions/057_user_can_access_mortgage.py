"""Add can_access_mortgage feature-flag to users.

Revision ID: 057
Revises: 056
Create Date: 2026-04-24

Hypotheek-toegang loskoppelen van is_admin (GJA-47). Elke user krijgt een
nieuw ``can_access_mortgage`` veld (0=uit, 1=aan). Default 0 voor alle
bestaande users — behalve de super-admin (of user_id=1 als fallback)
zodat de eigenaar niet per ongeluk zijn eigen hypotheek-sectie kwijtraakt
bij de upgrade. Andere admins die hypotheek nodig hebben zetten de flag
handmatig aan in /admin/users.
"""
import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import text


revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("users")}

    if "can_access_mortgage" not in cols:
        op.add_column(
            "users",
            sa.Column(
                "can_access_mortgage", sa.Integer(),
                nullable=False, server_default="0",
            ),
        )

    # Preserve hypotheek-toegang voor de huidige eigenaar van de instance.
    super_admin = (os.getenv("SUPER_ADMIN_USERNAME") or "").strip()
    if super_admin:
        bind.execute(
            text("UPDATE users SET can_access_mortgage = 1 WHERE username = :u"),
            {"u": super_admin},
        )
    else:
        bind.execute(text("UPDATE users SET can_access_mortgage = 1 WHERE id = 1"))


def downgrade() -> None:
    op.drop_column("users", "can_access_mortgage")
