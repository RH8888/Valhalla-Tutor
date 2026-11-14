"""stage_5_completion_audit

Revision ID: 9d5e31a9b201
Revises: 8c4f32b9e166
Create Date: 2026-11-14 20:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '9d5e31a9b201'
down_revision: Union[str, Sequence[str], None] = '8c4f32b9e166'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'completion_audit_logs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('assignment_id', sa.Uuid(), nullable=False),
        sa.Column('student_id', sa.Uuid(), nullable=False),
        sa.Column('performed_by_id', sa.Uuid(), nullable=False),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('recorded_completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('note', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['assignment_id'], ['plan_assignments.id'], name=op.f('fk_completion_audit_logs_assignment_id_plan_assignments'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], name=op.f('fk_completion_audit_logs_student_id_users'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['performed_by_id'], ['users.id'], name=op.f('fk_completion_audit_logs_performed_by_id_users'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_completion_audit_logs'))
    )
    op.create_index(op.f('ix_completion_audit_logs_assignment_id'), 'completion_audit_logs', ['assignment_id'], unique=False)
    op.create_index(op.f('ix_completion_audit_logs_student_id'), 'completion_audit_logs', ['student_id'], unique=False)
    op.create_index(op.f('ix_completion_audit_logs_performed_by_id'), 'completion_audit_logs', ['performed_by_id'], unique=False)
    op.create_index(op.f('ix_completion_audit_logs_action'), 'completion_audit_logs', ['action'], unique=False)
    op.create_index(op.f('ix_completion_audit_logs_created_at'), 'completion_audit_logs', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_table('completion_audit_logs')

