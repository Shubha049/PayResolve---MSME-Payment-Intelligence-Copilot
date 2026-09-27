"""add persisted idempotency keys for recovery automation actions

Revision ID: 003_recovery_action_idempotency
Revises: 002_recovery_actions
Create Date: 2026-09-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "003_recovery_action_idempotency"
down_revision: Union[str, None] = "002_recovery_actions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("recovery_actions", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.create_index(
        "uq_recovery_actions_idempotency_key",
        "recovery_actions",
        ["idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        mssql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_recovery_actions_idempotency_key", table_name="recovery_actions")
    op.drop_column("recovery_actions", "idempotency_key")
