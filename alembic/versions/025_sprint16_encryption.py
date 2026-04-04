"""Sprint 16: widen counterparty/counterparty_iban to Text for encrypted storage

Revision ID: 025
Revises: 024
Create Date: 2026-04-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "025"
down_revision: Union[str, None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Fernet-encrypted strings are longer than the originals; widen to Text
    op.alter_column("transactions", "counterparty",
                    existing_type=sa.String(255), type_=sa.Text(), nullable=True)
    op.alter_column("transactions", "counterparty_iban",
                    existing_type=sa.String(34), type_=sa.Text(), nullable=True)
    # description is already Text — no change needed


def downgrade() -> None:
    op.alter_column("transactions", "counterparty",
                    existing_type=sa.Text(), type_=sa.String(255), nullable=True)
    op.alter_column("transactions", "counterparty_iban",
                    existing_type=sa.Text(), type_=sa.String(34), nullable=True)
