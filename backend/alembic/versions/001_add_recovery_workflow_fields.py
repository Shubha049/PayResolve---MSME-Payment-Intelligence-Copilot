"""add recovery workflow fields to case and create promises_to_pay table

Revision ID: 001_recovery_workflow
Revises: 
Create Date: 2026-09-24

This migration adds Phase 1 Recovery Workflow support:
- Four new optional fields to the cases table
- New promises_to_pay table for structured promise tracking
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_recovery_workflow'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add recovery workflow fields to cases table and create promises_to_pay table.
    
    All fields are nullable to maintain backward compatibility with existing cases.
    """
    # Add recovery fields to cases table
    with op.batch_alter_table('cases', schema=None) as batch_op:
        batch_op.add_column(sa.Column('amount_in_recovery', sa.Numeric(precision=15, scale=2), nullable=True))
        batch_op.add_column(sa.Column('expected_payment_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('last_contact_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('next_follow_up_date', sa.Date(), nullable=True))
        
        # Add indexes for recovery queries
        batch_op.create_index('ix_cases_expected_payment_date', ['expected_payment_date'])
        batch_op.create_index('ix_cases_next_follow_up_date', ['next_follow_up_date'])

    # Create promises_to_pay table
    op.create_table('promises_to_pay',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('case_id', sa.String(length=36), nullable=False),
        sa.Column('promise_date', sa.Date(), nullable=False),
        sa.Column('promised_amount', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('status', sa.Enum('PENDING', 'FULFILLED', 'BROKEN', 'CANCELLED', name='promisestatus'), nullable=False),
        sa.Column('fulfilled_by_payment_id', sa.String(length=36), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['fulfilled_by_payment_id'], ['payments.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for promises_to_pay
    op.create_index('ix_promises_to_pay_id', 'promises_to_pay', ['id'])
    op.create_index('ix_promises_to_pay_organization_id', 'promises_to_pay', ['organization_id'])
    op.create_index('ix_promises_to_pay_case_id', 'promises_to_pay', ['case_id'])
    op.create_index('ix_promises_to_pay_promise_date', 'promises_to_pay', ['promise_date'])
    op.create_index('ix_promises_to_pay_status', 'promises_to_pay', ['status'])


def downgrade() -> None:
    """
    Remove recovery workflow fields and promises_to_pay table.
    """
    # Drop promises_to_pay table and indexes
    op.drop_index('ix_promises_to_pay_status', table_name='promises_to_pay')
    op.drop_index('ix_promises_to_pay_promise_date', table_name='promises_to_pay')
    op.drop_index('ix_promises_to_pay_case_id', table_name='promises_to_pay')
    op.drop_index('ix_promises_to_pay_organization_id', table_name='promises_to_pay')
    op.drop_index('ix_promises_to_pay_id', table_name='promises_to_pay')
    op.drop_table('promises_to_pay')
    
    # Remove recovery fields from cases table
    with op.batch_alter_table('cases', schema=None) as batch_op:
        batch_op.drop_index('ix_cases_next_follow_up_date')
        batch_op.drop_index('ix_cases_expected_payment_date')
        batch_op.drop_column('next_follow_up_date')
        batch_op.drop_column('last_contact_date')
        batch_op.drop_column('expected_payment_date')
        batch_op.drop_column('amount_in_recovery')
