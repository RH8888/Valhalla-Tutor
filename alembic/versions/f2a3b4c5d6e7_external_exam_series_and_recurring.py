"""external_exam_series_and_recurring

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-11-15 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add recurrence columns to exams
    with op.batch_alter_table('exams', schema=None) as batch_op:
        batch_op.add_column(sa.Column('first_exam_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('last_exam_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('recurrence_interval_weeks', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('recurrence_weekday', sa.Integer(), nullable=True))

    # 2. Add status & exception columns to exam_sessions
    with op.batch_alter_table('exam_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(length=20), server_default='SCHEDULED', nullable=False))
        batch_op.add_column(sa.Column('skip_reason', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('is_manually_added', sa.Boolean(), server_default=sa.text('false'), nullable=False))
        batch_op.add_column(sa.Column('sequence_order', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_exam_sessions_status'), ['status'], unique=False)
        batch_op.create_unique_constraint('uq_exam_session_date', ['exam_id', 'date'])

    # 3. Create exam_grade_track_configs table
    op.create_table(
        'exam_grade_track_configs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('exam_id', sa.Uuid(), nullable=False),
        sa.Column('grade', sa.String(length=20), nullable=False),
        sa.Column('track_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['exam_id'], ['exams.id'], name=op.f('fk_exam_grade_track_configs_exam_id_exams'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['track_id'], ['academic_tracks.id'], name=op.f('fk_exam_grade_track_configs_track_id_academic_tracks'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_exam_grade_track_configs')),
        sa.UniqueConstraint('exam_id', 'grade', 'track_id', name='uq_exam_grade_track_config'),
    )
    op.create_index(op.f('ix_exam_grade_track_configs_exam_id'), 'exam_grade_track_configs', ['exam_id'], unique=False)
    op.create_index(op.f('ix_exam_grade_track_configs_grade'), 'exam_grade_track_configs', ['grade'], unique=False)
    op.create_index(op.f('ix_exam_grade_track_configs_track_id'), 'exam_grade_track_configs', ['track_id'], unique=False)

    # 4. Update exam_reporting_groups for grade/track attachment & ordering
    with op.batch_alter_table('exam_reporting_groups', schema=None) as batch_op:
        batch_op.add_column(sa.Column('exam_grade_track_config_id', sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column('order_index', sa.Integer(), server_default='0', nullable=False))
        batch_op.alter_column('exam_session_id', nullable=True)
        batch_op.create_foreign_key(
            op.f('fk_exam_reporting_groups_exam_grade_track_config_id'),
            'exam_grade_track_configs',
            ['exam_grade_track_config_id'],
            ['id'],
            ondelete='CASCADE',
        )
        batch_op.create_index(batch_op.f('ix_exam_reporting_groups_exam_grade_track_config_id'), ['exam_grade_track_config_id'], unique=False)

    # 5. Create exam_series_assignments table
    op.create_table(
        'exam_series_assignments',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('exam_id', sa.Uuid(), nullable=False),
        sa.Column('student_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['exam_id'], ['exams.id'], name=op.f('fk_exam_series_assignments_exam_id_exams'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], name=op.f('fk_exam_series_assignments_student_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_exam_series_assignments')),
        sa.UniqueConstraint('exam_id', 'student_id', name='uq_exam_series_assignment'),
    )
    op.create_index(op.f('ix_exam_series_assignments_exam_id'), 'exam_series_assignments', ['exam_id'], unique=False)
    op.create_index(op.f('ix_exam_series_assignments_student_id'), 'exam_series_assignments', ['student_id'], unique=False)

    # 6. Create exam_session_audits table
    op.create_table(
        'exam_session_audits',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('exam_session_id', sa.Uuid(), nullable=False),
        sa.Column('actor_id', sa.Uuid(), nullable=True),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('reason', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['exam_session_id'], ['exam_sessions.id'], name=op.f('fk_exam_session_audits_exam_session_id_exam_sessions'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_exam_session_audits_actor_id_users'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_exam_session_audits')),
    )
    op.create_index(op.f('ix_exam_session_audits_exam_session_id'), 'exam_session_audits', ['exam_session_id'], unique=False)
    op.create_index(op.f('ix_exam_session_audits_actor_id'), 'exam_session_audits', ['actor_id'], unique=False)

    # 7. Create student_exam_group_results table
    op.create_table(
        'student_exam_group_results',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('student_exam_result_id', sa.Uuid(), nullable=False),
        sa.Column('reporting_group_id', sa.Uuid(), nullable=True),
        sa.Column('group_title', sa.String(length=100), nullable=False),
        sa.Column('percentage', sa.Float(), nullable=False),
        sa.Column('included_subject_names', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['student_exam_result_id'], ['student_exam_results.id'], name=op.f('fk_student_exam_group_results_student_exam_result_id_student_exam_results'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reporting_group_id'], ['exam_reporting_groups.id'], name=op.f('fk_student_exam_group_results_reporting_group_id_exam_reporting_groups'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_student_exam_group_results')),
    )
    op.create_index(op.f('ix_student_exam_group_results_student_exam_result_id'), 'student_exam_group_results', ['student_exam_result_id'], unique=False)
    op.create_index(op.f('ix_student_exam_group_results_reporting_group_id'), 'student_exam_group_results', ['reporting_group_id'], unique=False)

    # 8. Alter student_exam_results for grade/track snapshot and config snapshot
    with op.batch_alter_table('student_exam_results', schema=None) as batch_op:
        batch_op.add_column(sa.Column('grade', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('academic_track_id', sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column('config_snapshot', sa.Text(), nullable=True))
        batch_op.create_foreign_key(op.f('fk_student_exam_results_academic_track_id_academic_tracks'), 'academic_tracks', ['academic_track_id'], ['id'], ondelete='SET NULL')
        batch_op.create_index(batch_op.f('ix_student_exam_results_grade'), ['grade'], unique=False)
        batch_op.create_index(batch_op.f('ix_student_exam_results_academic_track_id'), ['academic_track_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('student_exam_results', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_student_exam_results_academic_track_id'))
        batch_op.drop_index(batch_op.f('ix_student_exam_results_grade'))
        batch_op.drop_constraint(op.f('fk_student_exam_results_academic_track_id_academic_tracks'), type_='foreignkey')
        batch_op.drop_column('config_snapshot')
        batch_op.drop_column('academic_track_id')
        batch_op.drop_column('grade')

    op.drop_table('student_exam_group_results')
    op.drop_table('exam_session_audits')
    op.drop_table('exam_series_assignments')

    with op.batch_alter_table('exam_reporting_groups', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_exam_reporting_groups_exam_grade_track_config_id'))
        batch_op.drop_constraint(op.f('fk_exam_reporting_groups_exam_grade_track_config_id'), type_='foreignkey')
        batch_op.drop_column('order_index')
        batch_op.drop_column('exam_grade_track_config_id')

    op.drop_table('exam_grade_track_configs')

    with op.batch_alter_table('exam_sessions', schema=None) as batch_op:
        batch_op.drop_constraint('uq_exam_session_date', type_='unique')
        batch_op.drop_index(batch_op.f('ix_exam_sessions_status'))
        batch_op.drop_column('sequence_order')
        batch_op.drop_column('is_manually_added')
        batch_op.drop_column('skip_reason')
        batch_op.drop_column('status')

    with op.batch_alter_table('exams', schema=None) as batch_op:
        batch_op.drop_column('recurrence_weekday')
        batch_op.drop_column('recurrence_interval_weeks')
        batch_op.drop_column('last_exam_date')
        batch_op.drop_column('first_exam_date')
