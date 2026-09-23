from alembic import op
import sqlalchemy as sa

revision = "063"
down_revision = "062"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("bank_connections", sa.Column("last_sync_status", sa.String(length=20), nullable=False, server_default="never"))
    op.add_column("bank_connections", sa.Column("last_sync_error", sa.Text(), nullable=True))

def downgrade():
    op.drop_column("bank_connections", "last_sync_error")
    op.drop_column("bank_connections", "last_sync_status")
