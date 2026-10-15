"""Rekeninggroepen: account_groups en accounts.group_id (ACT-55a).

Revision ID: 070
Revises: 069

Elke bestaande rekening krijgt een eigen groep met dezelfde naam; samenvoegen van groepen
gebeurt daarna door de gebruiker. Er worden geen transacties of categorieën aangeraakt.
"""
from alembic import op
import sqlalchemy as sa

revision = "070"
down_revision = "069"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "account_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_account_groups_user_id", "account_groups", ["user_id"])
    op.add_column("accounts", sa.Column("group_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_accounts_group_id", "accounts", "account_groups", ["group_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_accounts_group_id", "accounts", ["group_id"])

    bind = op.get_bind()
    accounts = sa.table(
        "accounts", sa.column("id", sa.Integer), sa.column("user_id", sa.Integer),
        sa.column("name", sa.String), sa.column("group_id", sa.Integer),
    )
    groups = sa.table(
        "account_groups", sa.column("id", sa.Integer), sa.column("user_id", sa.Integer),
        sa.column("name", sa.String), sa.column("created_at", sa.DateTime),
    )
    for account_id, user_id, name in bind.execute(sa.select(accounts.c.id, accounts.c.user_id, accounts.c.name)).all():
        result = bind.execute(
            groups.insert().values(user_id=user_id, name=name, created_at=sa.func.now()).returning(groups.c.id)
        )
        bind.execute(accounts.update().where(accounts.c.id == account_id).values(group_id=result.scalar_one()))


def downgrade():
    op.drop_index("ix_accounts_group_id", table_name="accounts")
    op.drop_constraint("fk_accounts_group_id", "accounts", type_="foreignkey")
    op.drop_column("accounts", "group_id")
    op.drop_index("ix_account_groups_user_id", table_name="account_groups")
    op.drop_table("account_groups")
