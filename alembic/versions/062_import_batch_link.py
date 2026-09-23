from alembic import op
import sqlalchemy as sa

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("transactions", sa.Column("import_batch_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_transactions_import_batch", "transactions", "import_batches", ["import_batch_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_transactions_import_batch_id", "transactions", ["import_batch_id"])

def downgrade():
    op.drop_index("ix_transactions_import_batch_id", table_name="transactions")
    op.drop_constraint("fk_transactions_import_batch", "transactions", type_="foreignkey")
    op.drop_column("transactions", "import_batch_id")
