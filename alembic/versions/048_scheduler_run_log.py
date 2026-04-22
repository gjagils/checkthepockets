"""Add scheduler_run_log for admin scheduler dashboard.

Revision ID: 048
Revises: 047
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa


revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "scheduler_run_log" in inspector.get_table_names():
        return

    op.create_table(
        "scheduler_run_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("summary", sa.Text(), nullable=True),
    )
    op.create_index("ix_scheduler_run_log_job_id", "scheduler_run_log", ["job_id"])
    op.create_index("ix_scheduler_run_log_started_at", "scheduler_run_log", ["started_at"])


def downgrade():
    try:
        op.drop_index("ix_scheduler_run_log_started_at", table_name="scheduler_run_log")
        op.drop_index("ix_scheduler_run_log_job_id", table_name="scheduler_run_log")
    except Exception:
        pass
    op.drop_table("scheduler_run_log")
