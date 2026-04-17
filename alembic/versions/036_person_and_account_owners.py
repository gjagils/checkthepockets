"""Rename portfolio_persons to persons, add sort_order, and introduce account_owners.

Revision ID: 036
Revises: 035
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa


revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # 1. Rename portfolio_persons -> persons (Postgres houdt FKs intact bij rename).
    #    Bij een verse database is portfolio_persons er al; bij een DB waar
    #    migratie 012 om wat voor reden niet is gelopen, slaan we de rename over
    #    en maken we direct de nieuwe tabel.
    if "portfolio_persons" in tables and "persons" not in tables:
        op.rename_table("portfolio_persons", "persons")
    elif "persons" not in tables:
        op.create_table(
            "persons",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )

    # 2. sort_order toevoegen (idempotent)
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("persons")}
    if "sort_order" not in cols:
        op.add_column(
            "persons",
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        )

    # 3. account_owners koppeltabel (many-to-many Account <-> Person)
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "account_owners" not in tables:
        op.create_table(
            "account_owners",
            sa.Column(
                "account_id",
                sa.Integer(),
                sa.ForeignKey("accounts.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "person_id",
                sa.Integer(),
                sa.ForeignKey("persons.id", ondelete="CASCADE"),
                primary_key=True,
            ),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "account_owners" in tables:
        op.drop_table("account_owners")

    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("persons")} if "persons" in tables else set()
    if "sort_order" in cols:
        try:
            op.drop_column("persons", "sort_order")
        except Exception:
            pass

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "persons" in tables and "portfolio_persons" not in tables:
        op.rename_table("persons", "portfolio_persons")
