"""Make transaction import identity unique per account."""
from alembic import op
import sqlalchemy as sa

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for constraint in inspector.get_unique_constraints("transactions"):
        if set(constraint.get("column_names") or ()) == {"import_hash"} and constraint.get("name"):
            op.drop_constraint(constraint["name"], "transactions", type_="unique")
    inspector = sa.inspect(bind)
    if not any(set(c.get("column_names") or ()) == {"account_id", "import_hash"}
               for c in inspector.get_unique_constraints("transactions")):
        op.create_unique_constraint("uq_transaction_account_import_hash", "transactions", ["account_id", "import_hash"])


def downgrade():
    op.drop_constraint("uq_transaction_account_import_hash", "transactions", type_="unique")
    op.create_unique_constraint("uq_transactions_import_hash", "transactions", ["import_hash"])
