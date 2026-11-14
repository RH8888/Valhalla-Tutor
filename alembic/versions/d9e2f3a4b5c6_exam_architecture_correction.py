"""exam_architecture_correction

Revision ID: d9e2f3a4b5c6
Revises: c8f1e2a3b456
Create Date: 2026-11-14 23:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd9e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'c8f1e2a3b456'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Alter exam_sessions: add grade and submission_deadline
    with op.batch_alter_table('exam_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('grade', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('submission_deadline', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(batch_op.f('ix_exam_sessions_grade'), ['grade'], unique=False)

    # 2. Alter student_exam_results: add report card upload columns
    with op.batch_alter_table('student_exam_results', schema=None) as batch_op:
        batch_op.add_column(sa.Column('report_card_file_path', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('report_card_file_name', sa.String(length=255), nullable=True))

    # 3. Create external_exam_assignments table
    op.create_table(
        'external_exam_assignments',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('exam_session_id', sa.Uuid(), nullable=False),
        sa.Column('student_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['exam_session_id'], ['exam_sessions.id'], name=op.f('fk_external_exam_assignments_exam_session_id_exam_sessions'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], name=op.f('fk_external_exam_assignments_student_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_external_exam_assignments')),
        sa.UniqueConstraint('exam_session_id', 'student_id', name='uq_external_exam_assignment'),
    )
    op.create_index(op.f('ix_external_exam_assignments_exam_session_id'), 'external_exam_assignments', ['exam_session_id'], unique=False)
    op.create_index(op.f('ix_external_exam_assignments_student_id'), 'external_exam_assignments', ['student_id'], unique=False)

    # 4. Create exam_reporting_groups & exam_reporting_group_subjects
    op.create_table(
        'exam_reporting_groups',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('exam_session_id', sa.Uuid(), nullable=False),
        sa.Column('title', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['exam_session_id'], ['exam_sessions.id'], name=op.f('fk_exam_reporting_groups_exam_session_id_exam_sessions'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_exam_reporting_groups')),
    )
    op.create_table(
        'exam_reporting_group_subjects',
        sa.Column('group_id', sa.Uuid(), nullable=False),
        sa.Column('subject_id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['group_id'], ['exam_reporting_groups.id'], name=op.f('fk_exam_reporting_group_subjects_group_id_exam_reporting_groups'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], name=op.f('fk_exam_reporting_group_subjects_subject_id_subjects'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('group_id', 'subject_id', name=op.f('pk_exam_reporting_group_subjects')),
    )

    # 5. Create historical_exam_results & historical_exam_subject_results
    op.create_table(
        'historical_exam_results',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('student_id', sa.Uuid(), nullable=False),
        sa.Column('exam_name', sa.String(length=150), nullable=False),
        sa.Column('exam_date', sa.Date(), nullable=False),
        sa.Column('grade', sa.String(length=20), nullable=True),
        sa.Column('academic_track_id', sa.Uuid(), nullable=True),
        sa.Column('overall_rank', sa.Integer(), nullable=True),
        sa.Column('notes', sa.String(length=500), nullable=True),
        sa.Column('report_card_file_path', sa.String(length=500), nullable=True),
        sa.Column('report_card_file_name', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['academic_track_id'], ['academic_tracks.id'], name=op.f('fk_historical_exam_results_academic_track_id_academic_tracks'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], name=op.f('fk_historical_exam_results_student_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_historical_exam_results')),
    )
    op.create_index(op.f('ix_historical_exam_results_exam_date'), 'historical_exam_results', ['exam_date'], unique=False)
    op.create_index(op.f('ix_historical_exam_results_exam_name'), 'historical_exam_results', ['exam_name'], unique=False)
    op.create_index(op.f('ix_historical_exam_results_student_id'), 'historical_exam_results', ['student_id'], unique=False)

    op.create_table(
        'historical_exam_subject_results',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('historical_exam_result_id', sa.Uuid(), nullable=False),
        sa.Column('subject_name', sa.String(length=100), nullable=False),
        sa.Column('percentage', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['historical_exam_result_id'], ['historical_exam_results.id'], name=op.f('fk_historical_exam_subject_results_historical_exam_result_id_historical_exam_results'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_historical_exam_subject_results')),
    )
    op.create_index(op.f('ix_historical_exam_subject_results_historical_exam_result_id'), 'historical_exam_subject_results', ['historical_exam_result_id'], unique=False)

    # 6. Create practice_exams & practice_exam_booklets
    op.create_table(
        'practice_exams',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('title', sa.String(length=150), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('grade', sa.String(length=20), nullable=False),
        sa.Column('academic_track_id', sa.Uuid(), nullable=False),
        sa.Column('is_timed', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['academic_track_id'], ['academic_tracks.id'], name=op.f('fk_practice_exams_academic_track_id_academic_tracks'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_practice_exams')),
    )
    op.create_index(op.f('ix_practice_exams_grade'), 'practice_exams', ['grade'], unique=False)
    op.create_index(op.f('ix_practice_exams_academic_track_id'), 'practice_exams', ['academic_track_id'], unique=False)
    op.create_index(op.f('ix_practice_exams_title'), 'practice_exams', ['title'], unique=False)

    op.create_table(
        'practice_exam_booklets',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('practice_exam_id', sa.Uuid(), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=150), nullable=False),
        sa.Column('pdf_file_path', sa.String(length=500), nullable=False),
        sa.Column('pdf_file_name', sa.String(length=255), nullable=False),
        sa.Column('question_start', sa.Integer(), nullable=False),
        sa.Column('question_end', sa.Integer(), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['practice_exam_id'], ['practice_exams.id'], name=op.f('fk_practice_exam_booklets_practice_exam_id_practice_exams'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_practice_exam_booklets')),
        sa.UniqueConstraint('practice_exam_id', 'order_index', name='uq_practice_booklet_order'),
    )
    op.create_index(op.f('ix_practice_exam_booklets_practice_exam_id'), 'practice_exam_booklets', ['practice_exam_id'], unique=False)

    # 7. Create practice_exam_reporting_groups & practice_exam_questions
    op.create_table(
        'practice_exam_reporting_groups',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('practice_exam_id', sa.Uuid(), nullable=False),
        sa.Column('title', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['practice_exam_id'], ['practice_exams.id'], name=op.f('fk_practice_exam_reporting_groups_practice_exam_id_practice_exams'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_practice_exam_reporting_groups')),
    )
    op.create_index(op.f('ix_practice_exam_reporting_groups_practice_exam_id'), 'practice_exam_reporting_groups', ['practice_exam_id'], unique=False)

    op.create_table(
        'practice_exam_questions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('practice_exam_id', sa.Uuid(), nullable=False),
        sa.Column('question_number', sa.Integer(), nullable=False),
        sa.Column('correct_choice', sa.Integer(), nullable=False),
        sa.Column('subject_id', sa.Uuid(), nullable=False),
        sa.Column('reporting_group_id', sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(['practice_exam_id'], ['practice_exams.id'], name=op.f('fk_practice_exam_questions_practice_exam_id_practice_exams'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reporting_group_id'], ['practice_exam_reporting_groups.id'], name=op.f('fk_practice_exam_questions_reporting_group_id_practice_exam_reporting_groups'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], name=op.f('fk_practice_exam_questions_subject_id_subjects'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_practice_exam_questions')),
        sa.UniqueConstraint('practice_exam_id', 'question_number', name='uq_practice_question_number'),
    )
    op.create_index(op.f('ix_practice_exam_questions_practice_exam_id'), 'practice_exam_questions', ['practice_exam_id'], unique=False)
    op.create_index(op.f('ix_practice_exam_questions_subject_id'), 'practice_exam_questions', ['subject_id'], unique=False)

    # 8. Create practice_exam_assignments
    op.create_table(
        'practice_exam_assignments',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('practice_exam_id', sa.Uuid(), nullable=False),
        sa.Column('student_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['practice_exam_id'], ['practice_exams.id'], name=op.f('fk_practice_exam_assignments_practice_exam_id_practice_exams'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], name=op.f('fk_practice_exam_assignments_student_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_practice_exam_assignments')),
        sa.UniqueConstraint('practice_exam_id', 'student_id', name='uq_practice_assignment'),
    )
    op.create_index(op.f('ix_practice_exam_assignments_practice_exam_id'), 'practice_exam_assignments', ['practice_exam_id'], unique=False)
    op.create_index(op.f('ix_practice_exam_assignments_student_id'), 'practice_exam_assignments', ['student_id'], unique=False)

    # 9. Create student_practice_attempts, booklet_attempts, answers
    op.create_table(
        'student_practice_attempts',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('student_id', sa.Uuid(), nullable=False),
        sa.Column('practice_exam_id', sa.Uuid(), nullable=False),
        sa.Column('is_timed', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='IN_PROGRESS', nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('total_correct', sa.Integer(), server_default='0', nullable=False),
        sa.Column('total_incorrect', sa.Integer(), server_default='0', nullable=False),
        sa.Column('total_unanswered', sa.Integer(), server_default='0', nullable=False),
        sa.Column('overall_percentage', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['practice_exam_id'], ['practice_exams.id'], name=op.f('fk_student_practice_attempts_practice_exam_id_practice_exams'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], name=op.f('fk_student_practice_attempts_student_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_student_practice_attempts')),
    )
    op.create_index(op.f('ix_student_practice_attempts_practice_exam_id'), 'student_practice_attempts', ['practice_exam_id'], unique=False)
    op.create_index(op.f('ix_student_practice_attempts_status'), 'student_practice_attempts', ['status'], unique=False)
    op.create_index(op.f('ix_student_practice_attempts_student_id'), 'student_practice_attempts', ['student_id'], unique=False)

    op.create_table(
        'student_practice_booklet_attempts',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('attempt_id', sa.Uuid(), nullable=False),
        sa.Column('booklet_id', sa.Uuid(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_locked', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['attempt_id'], ['student_practice_attempts.id'], name=op.f('fk_student_practice_booklet_attempts_attempt_id_student_practice_attempts'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['booklet_id'], ['practice_exam_booklets.id'], name=op.f('fk_student_practice_booklet_attempts_booklet_id_practice_exam_booklets'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_student_practice_booklet_attempts')),
        sa.UniqueConstraint('attempt_id', 'booklet_id', name='uq_attempt_booklet'),
    )
    op.create_index(op.f('ix_student_practice_booklet_attempts_attempt_id'), 'student_practice_booklet_attempts', ['attempt_id'], unique=False)
    op.create_index(op.f('ix_student_practice_booklet_attempts_booklet_id'), 'student_practice_booklet_attempts', ['booklet_id'], unique=False)

    op.create_table(
        'student_practice_answers',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('attempt_id', sa.Uuid(), nullable=False),
        sa.Column('booklet_attempt_id', sa.Uuid(), nullable=False),
        sa.Column('question_number', sa.Integer(), nullable=False),
        sa.Column('selected_choice', sa.Integer(), nullable=True),
        sa.Column('is_correct', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['attempt_id'], ['student_practice_attempts.id'], name=op.f('fk_student_practice_answers_attempt_id_student_practice_attempts'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['booklet_attempt_id'], ['student_practice_booklet_attempts.id'], name=op.f('fk_student_practice_answers_booklet_attempt_id_student_practice_booklet_attempts'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_student_practice_answers')),
        sa.UniqueConstraint('attempt_id', 'question_number', name='uq_attempt_question_number'),
    )
    op.create_index(op.f('ix_student_practice_answers_attempt_id'), 'student_practice_answers', ['attempt_id'], unique=False)
    op.create_index(op.f('ix_student_practice_answers_booklet_attempt_id'), 'student_practice_answers', ['booklet_attempt_id'], unique=False)


def downgrade() -> None:
    op.drop_table('student_practice_answers')
    op.drop_table('student_practice_booklet_attempts')
    op.drop_table('student_practice_attempts')
    op.drop_table('practice_exam_assignments')
    op.drop_table('practice_exam_questions')
    op.drop_table('practice_exam_reporting_groups')
    op.drop_table('practice_exam_booklets')
    op.drop_table('practice_exams')
    op.drop_table('historical_exam_subject_results')
    op.drop_table('historical_exam_results')
    op.drop_table('exam_reporting_group_subjects')
    op.drop_table('exam_reporting_groups')
    op.drop_table('external_exam_assignments')
    with op.batch_alter_table('student_exam_results', schema=None) as batch_op:
        batch_op.drop_column('report_card_file_name')
        batch_op.drop_column('report_card_file_path')
    with op.batch_alter_table('exam_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_exam_sessions_grade'))
        batch_op.drop_column('submission_deadline')
        batch_op.drop_column('grade')
