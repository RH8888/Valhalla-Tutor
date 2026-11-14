"""external_exams_lifecycle_and_audit

Revision ID: a1b2c3d4e5f6
Revises: f2a3b4c5d6e7
Create Date: 2026-11-15 01:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add fields to exams
    with op.batch_alter_table('exams', schema=None) as batch_op:
        batch_op.add_column(sa.Column('submission_days_after_exam', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('is_archived', sa.Boolean(), server_default=sa.text('false'), nullable=False))

    # 2. Add fields to exam_sessions
    with op.batch_alter_table('exam_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('allow_late_submission', sa.Boolean(), server_default=sa.text('true'), nullable=False))

    # 3. Add fields to student_exam_results
    with op.batch_alter_table('student_exam_results', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_reviewed', sa.Boolean(), server_default=sa.text('false'), nullable=False))
        batch_op.add_column(sa.Column('reviewed_by_id', sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('is_late', sa.Boolean(), server_default=sa.text('false'), nullable=False))
        batch_op.add_column(sa.Column('is_tutor_corrected', sa.Boolean(), server_default=sa.text('false'), nullable=False))
        batch_op.create_foreign_key('fk_student_exam_results_reviewed_by', 'users', ['reviewed_by_id'], ['id'], ondelete='SET NULL')

    # 4. Create exam_audit_logs table
    op.create_table(
        'exam_audit_logs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('actor_id', sa.Uuid(), nullable=True),
        sa.Column('entity_type', sa.String(length=50), nullable=False),
        sa.Column('entity_id', sa.Uuid(), nullable=False),
        sa.Column('exam_id', sa.Uuid(), nullable=True),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('previous_value', sa.Text(), nullable=True),
        sa.Column('new_value', sa.Text(), nullable=True),
        sa.Column('reason', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['exam_id'], ['exams.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_exam_audit_logs_actor_id'), 'exam_audit_logs', ['actor_id'], unique=False)
    op.create_index(op.f('ix_exam_audit_logs_entity_type'), 'exam_audit_logs', ['entity_type'], unique=False)
    op.create_index(op.f('ix_exam_audit_logs_entity_id'), 'exam_audit_logs', ['entity_id'], unique=False)
    op.create_index(op.f('ix_exam_audit_logs_exam_id'), 'exam_audit_logs', ['exam_id'], unique=False)
    op.create_index(op.f('ix_exam_audit_logs_action'), 'exam_audit_logs', ['action'], unique=False)
    op.create_index(op.f('ix_exam_audit_logs_created_at'), 'exam_audit_logs', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_exam_audit_logs_created_at'), table_name='exam_audit_logs')
    op.drop_index(op.f('ix_exam_audit_logs_action'), table_name='exam_audit_logs')
    op.drop_index(op.f('ix_exam_audit_logs_exam_id'), table_name='exam_audit_logs')
    op.drop_index(op.f('ix_exam_audit_logs_entity_id'), table_name='exam_audit_logs')
    op.drop_index(op.f('ix_exam_audit_logs_entity_type'), table_name='exam_audit_logs')
    op.drop_index(op.f('ix_exam_audit_logs_actor_id'), table_name='exam_audit_logs')
    op.drop_table('exam_audit_logs')

    with op.batch_alter_table('student_exam_results', schema=None) as batch_op:
        batch_op.drop_constraint('fk_student_exam_results_reviewed_by', type_='foreignkey')
        batch_op.drop_column('is_tutor_corrected')
        batch_op.drop_column('is_late')
        batch_op.drop_column('reviewed_at')
        batch_op.drop_column('reviewed_by_id')
        batch_op.drop_column('is_reviewed')

    with op.batch_alter_table('exam_sessions', schema=None) as batch_op:
        batch_op.drop_column('allow_late_submission')

    with op.batch_alter_table('exams', schema=None) as batch_op:
        batch_op.drop_column('is_archived')
        batch_op.drop_column('submission_days_after_exam')
