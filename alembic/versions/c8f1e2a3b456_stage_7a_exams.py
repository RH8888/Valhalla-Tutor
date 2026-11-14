"""stage_7a_exams

Revision ID: c8f1e2a3b456
Revises: b5e89a1c2d34
Create Date: 2026-11-14 23:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c8f1e2a3b456'
down_revision: Union[str, Sequence[str], None] = 'b5e89a1c2d34'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create exams table
    op.create_table(
        'exams',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('title', sa.String(length=150), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_exams')),
    )
    op.create_index(op.f('ix_exams_title'), 'exams', ['title'], unique=False)

    # 2. Create exam_sessions table
    op.create_table(
        'exam_sessions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('exam_id', sa.Uuid(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['exam_id'], ['exams.id'], name=op.f('fk_exam_sessions_exam_id_exams'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_exam_sessions')),
    )
    op.create_index(op.f('ix_exam_sessions_date'), 'exam_sessions', ['date'], unique=False)
    op.create_index(op.f('ix_exam_sessions_exam_id'), 'exam_sessions', ['exam_id'], unique=False)

    # 3. Create exam_track_configurations table
    op.create_table(
        'exam_track_configurations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('exam_session_id', sa.Uuid(), nullable=False),
        sa.Column('track_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['exam_session_id'], ['exam_sessions.id'], name=op.f('fk_exam_track_configurations_exam_session_id_exam_sessions'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['track_id'], ['academic_tracks.id'], name=op.f('fk_exam_track_configurations_track_id_academic_tracks'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_exam_track_configurations')),
        sa.UniqueConstraint('exam_session_id', 'track_id', name='uq_exam_track_config'),
    )
    op.create_index(op.f('ix_exam_track_configurations_exam_session_id'), 'exam_track_configurations', ['exam_session_id'], unique=False)
    op.create_index(op.f('ix_exam_track_configurations_track_id'), 'exam_track_configurations', ['track_id'], unique=False)

    # 4. Create exam_subject_configurations table
    op.create_table(
        'exam_subject_configurations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('exam_track_config_id', sa.Uuid(), nullable=False),
        sa.Column('subject_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['exam_track_config_id'], ['exam_track_configurations.id'], name=op.f('fk_exam_subject_configurations_exam_track_config_id_exam_track_configurations'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], name=op.f('fk_exam_subject_configurations_subject_id_subjects'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_exam_subject_configurations')),
        sa.UniqueConstraint('exam_track_config_id', 'subject_id', name='uq_exam_subject_config'),
    )
    op.create_index(op.f('ix_exam_subject_configurations_exam_track_config_id'), 'exam_subject_configurations', ['exam_track_config_id'], unique=False)
    op.create_index(op.f('ix_exam_subject_configurations_subject_id'), 'exam_subject_configurations', ['subject_id'], unique=False)

    # 5. Create student_exam_results table
    op.create_table(
        'student_exam_results',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('student_id', sa.Uuid(), nullable=False),
        sa.Column('exam_session_id', sa.Uuid(), nullable=False),
        sa.Column('overall_rank', sa.Integer(), nullable=True),
        sa.Column('notes', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['exam_session_id'], ['exam_sessions.id'], name=op.f('fk_student_exam_results_exam_session_id_exam_sessions'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], name=op.f('fk_student_exam_results_student_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_student_exam_results')),
        sa.UniqueConstraint('student_id', 'exam_session_id', name='uq_student_exam_session'),
    )
    op.create_index(op.f('ix_student_exam_results_exam_session_id'), 'student_exam_results', ['exam_session_id'], unique=False)
    op.create_index(op.f('ix_student_exam_results_student_id'), 'student_exam_results', ['student_id'], unique=False)

    # 6. Create student_exam_subject_results table
    op.create_table(
        'student_exam_subject_results',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('student_exam_result_id', sa.Uuid(), nullable=False),
        sa.Column('subject_id', sa.Uuid(), nullable=False),
        sa.Column('correct_answers', sa.Integer(), nullable=False),
        sa.Column('incorrect_answers', sa.Integer(), nullable=False),
        sa.Column('percentage', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['student_exam_result_id'], ['student_exam_results.id'], name=op.f('fk_student_exam_subject_results_student_exam_result_id_student_exam_results'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], name=op.f('fk_student_exam_subject_results_subject_id_subjects'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_student_exam_subject_results')),
        sa.UniqueConstraint('student_exam_result_id', 'subject_id', name='uq_result_subject'),
    )
    op.create_index(op.f('ix_student_exam_subject_results_student_exam_result_id'), 'student_exam_subject_results', ['student_exam_result_id'], unique=False)
    op.create_index(op.f('ix_student_exam_subject_results_subject_id'), 'student_exam_subject_results', ['subject_id'], unique=False)


def downgrade() -> None:
    op.drop_table('student_exam_subject_results')
    op.drop_table('student_exam_results')
    op.drop_table('exam_subject_configurations')
    op.drop_table('exam_track_configurations')
    op.drop_table('exam_sessions')
    op.drop_table('exams')
