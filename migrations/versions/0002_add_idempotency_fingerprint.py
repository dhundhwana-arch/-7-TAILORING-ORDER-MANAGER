"""Add idempotency_fingerprint column to orders table.

Revision ID: 0002_idempotency_fingerprint
Revises: 0001_initial
Create Date: 2026-11-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_idempotency_fingerprint"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("idempotency_fingerprint", sa.String(length=64), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.drop_column("idempotency_fingerprint")
