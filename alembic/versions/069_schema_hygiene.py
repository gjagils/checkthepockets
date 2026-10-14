"""Schema hygiene: indexes the model now declares, and a unique index for global category names.

Revision ID: 069
Revises: 068

- Indexes on foreign-key columns that queries filter on: transactions.recurring_id / transfer_id and
  user_id on accounts, categories and persons. (The indexes that already existed in the database
  are now also declared on the models; nothing changes for them.)
- uq_user_account_category treats NULL account_id values as distinct, so the categories that belong to
  no account ("global" ones) could share a name. A partial unique index closes that. It is created
  only when the existing data has no such duplicates; otherwise it is skipped with a notice (the
  duplicates are then a manual clean-up) instead of failing the deployment or editing user data.
"""
from alembic import op
import sqlalchemy as sa

revision = "069"
down_revision = "068"
branch_labels = None
depends_on = None

NEW_INDEXES = (
    ("ix_transactions_recurring_id", "transactions", ["recurring_id"]),
    ("ix_transactions_transfer_id", "transactions", ["transfer_id"]),
    ("ix_accounts_user_id", "accounts", ["user_id"]),
    ("ix_categories_user_id", "categories", ["user_id"]),
    ("ix_persons_user_id", "persons", ["user_id"]),
)
GLOBAL_CATEGORY_INDEX = "uq_user_category_global_name"


def _existing_indexes(table):
    return {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade():
    for name, table, columns in NEW_INDEXES:
        if name not in _existing_indexes(table):
            op.create_index(name, table, columns)

    bind = op.get_bind()
    duplicates = bind.execute(sa.text(
        "SELECT COUNT(*) FROM (SELECT 1 FROM categories WHERE account_id IS NULL "
        "GROUP BY user_id, name HAVING COUNT(*) > 1) d"
    )).scalar()
    if duplicates:
        print(f"[069] {duplicates} global category name(s) occur more than once; "
              f"{GLOBAL_CATEGORY_INDEX} was NOT created. Merge those categories, then create the index.")
    elif GLOBAL_CATEGORY_INDEX not in _existing_indexes("categories"):
        op.create_index(
            GLOBAL_CATEGORY_INDEX, "categories", ["user_id", "name"], unique=True,
            postgresql_where=sa.text("account_id IS NULL"),
        )


def downgrade():
    if GLOBAL_CATEGORY_INDEX in _existing_indexes("categories"):
        op.drop_index(GLOBAL_CATEGORY_INDEX, table_name="categories")
    for name, table, _columns in reversed(NEW_INDEXES):
        if name in _existing_indexes(table):
            op.drop_index(name, table_name=table)
