"""add recovery actions table

Revision ID: 002_recovery_actions
Revises: 001_recovery_workflow
Create Date: 2026-09-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "002_recovery_actions"
down_revision: Union[str, None] = "001_recovery_workflow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recovery_actions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("action_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("next_follow_up_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recovery_actions_organization_id", "recovery_actions", ["organization_id"])
    op.create_index("ix_recovery_actions_case_id", "recovery_actions", ["case_id"])
    op.create_index("ix_recovery_actions_action_type", "recovery_actions", ["action_type"])
    op.create_index("ix_recovery_actions_action_date", "recovery_actions", ["action_date"])


def downgrade() -> None:
    op.drop_index("ix_recovery_actions_action_date", table_name="recovery_actions")
    op.drop_index("ix_recovery_actions_action_type", table_name="recovery_actions")
    op.drop_index("ix_recovery_actions_case_id", table_name="recovery_actions")
    op.drop_index("ix_recovery_actions_organization_id", table_name="recovery_actions")
    op.drop_table("recovery_actions")
