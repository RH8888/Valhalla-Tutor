"""stage_4_study_plans

Revision ID: 8c4f32b9e166
Revises: 7b3e21a8d055
Create Date: 2026-11-14 18:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '8c4f32b9e166'
down_revision: Union[str, Sequence[str], None] = '7b3e21a8d055'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'study_plans',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('student_id', sa.Uuid(), nullable=False),
        sa.Column('tutor_id', sa.Uuid(), nullable=False),
        sa.Column('title', sa.String(length=150), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('end_date >= start_date', name=op.f('ck_study_plans_date_range')),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], name=op.f('fk_study_plans_student_id_users'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tutor_id'], ['users.id'], name=op.f('fk_study_plans_tutor_id_users'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_study_plans'))
    )
    op.create_index(op.f('ix_study_plans_student_id'), 'study_plans', ['student_id'], unique=False)
    op.create_index(op.f('ix_study_plans_tutor_id'), 'study_plans', ['tutor_id'], unique=False)
    op.create_index(op.f('ix_study_plans_start_date'), 'study_plans', ['start_date'], unique=False)
    op.create_index(op.f('ix_study_plans_status'), 'study_plans', ['status'], unique=False)

    op.create_table(
        'plan_assignments',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('study_plan_id', sa.Uuid(), nullable=False),
        sa.Column('student_id', sa.Uuid(), nullable=False),
        sa.Column('subject_id', sa.Uuid(), nullable=False),
        sa.Column('task_type', sa.String(length=20), nullable=False),
        sa.Column('scheduled_date', sa.Date(), nullable=False),
        sa.Column('display_order', sa.Integer(), nullable=False, default=1),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('recommended_duration_minutes', sa.Integer(), nullable=False, default=0),
        sa.Column('estimated_duration_minutes', sa.Integer(), nullable=True),
        sa.Column('is_estimated', sa.Boolean(), nullable=False, default=False),
        sa.Column('course_id', sa.Uuid(), nullable=True),
        sa.Column('course_chapter_id', sa.Uuid(), nullable=True),
        sa.Column('video_start_num', sa.Integer(), nullable=True),
        sa.Column('video_end_num', sa.Integer(), nullable=True),
        sa.Column('video_count', sa.Integer(), nullable=True),
        sa.Column('course_name_snapshot', sa.String(length=200), nullable=True),
        sa.Column('course_chapter_name_snapshot', sa.String(length=200), nullable=True),
        sa.Column('book_id', sa.Uuid(), nullable=True),
        sa.Column('book_chapter_id', sa.Uuid(), nullable=True),
        sa.Column('test_start_num', sa.Integer(), nullable=True),
        sa.Column('test_end_num', sa.Integer(), nullable=True),
        sa.Column('test_count', sa.Integer(), nullable=True),
        sa.Column('book_title_snapshot', sa.String(length=200), nullable=True),
        sa.Column('book_chapter_title_snapshot', sa.String(length=200), nullable=True),
        sa.Column('is_completed', sa.Boolean(), nullable=False, default=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('recommended_duration_minutes >= 0', name=op.f('ck_plan_assignments_duration_non_negative')),
        sa.ForeignKeyConstraint(['study_plan_id'], ['study_plans.id'], name=op.f('fk_plan_assignments_study_plan_id_study_plans'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], name=op.f('fk_plan_assignments_student_id_users'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], name=op.f('fk_plan_assignments_subject_id_subjects'), ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], name=op.f('fk_plan_assignments_course_id_courses'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['course_chapter_id'], ['course_chapters.id'], name=op.f('fk_plan_assignments_course_chapter_id_course_chapters'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['book_id'], ['books.id'], name=op.f('fk_plan_assignments_book_id_books'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['book_chapter_id'], ['book_chapters.id'], name=op.f('fk_plan_assignments_book_chapter_id_book_chapters'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_plan_assignments'))
    )
    op.create_index(op.f('ix_plan_assignments_study_plan_id'), 'plan_assignments', ['study_plan_id'], unique=False)
    op.create_index(op.f('ix_plan_assignments_student_id'), 'plan_assignments', ['student_id'], unique=False)
    op.create_index(op.f('ix_plan_assignments_subject_id'), 'plan_assignments', ['subject_id'], unique=False)
    op.create_index(op.f('ix_plan_assignments_task_type'), 'plan_assignments', ['task_type'], unique=False)
    op.create_index(op.f('ix_plan_assignments_scheduled_date'), 'plan_assignments', ['scheduled_date'], unique=False)
    op.create_index(op.f('ix_plan_assignments_is_completed'), 'plan_assignments', ['is_completed'], unique=False)


def downgrade() -> None:
    op.drop_table('plan_assignments')
    op.drop_table('study_plans')
