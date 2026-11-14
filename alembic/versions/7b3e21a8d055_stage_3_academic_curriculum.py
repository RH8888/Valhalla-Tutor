"""stage_3_academic_curriculum

Revision ID: 7b3e21a8d055
Revises: 4ae0d5b1b806
Create Date: 2026-11-14 17:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '7b3e21a8d055'
down_revision: Union[str, Sequence[str], None] = '4ae0d5b1b806'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('subjects',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_subjects')),
        sa.UniqueConstraint('name', name=op.f('uq_subjects_name'))
    )
    op.create_index(op.f('ix_subjects_name'), 'subjects', ['name'], unique=True)

    op.create_table('academic_tracks',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_academic_tracks')),
        sa.UniqueConstraint('name', name=op.f('uq_academic_tracks_name'))
    )
    op.create_index(op.f('ix_academic_tracks_name'), 'academic_tracks', ['name'], unique=True)

    op.create_table('track_subjects',
        sa.Column('track_id', sa.Uuid(), nullable=False),
        sa.Column('subject_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['track_id'], ['academic_tracks.id'], name=op.f('fk_track_subjects_track_id_academic_tracks'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], name=op.f('fk_track_subjects_subject_id_subjects'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('track_id', 'subject_id', name=op.f('pk_track_subjects'))
    )

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('academic_track_id', sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column('is_subjects_customized', sa.Boolean(), server_default=sa.text('false'), nullable=False))
        batch_op.create_foreign_key(batch_op.f('fk_users_academic_track_id_academic_tracks'), 'academic_tracks', ['academic_track_id'], ['id'], ondelete='SET NULL')

    op.create_table('student_custom_subjects',
        sa.Column('student_id', sa.Uuid(), nullable=False),
        sa.Column('subject_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], name=op.f('fk_student_custom_subjects_student_id_users'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], name=op.f('fk_student_custom_subjects_subject_id_subjects'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('student_id', 'subject_id', name=op.f('pk_student_custom_subjects'))
    )

    op.create_table('courses',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('subject_id', sa.Uuid(), nullable=False),
        sa.Column('teacher_name', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('grade', sa.String(length=50), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], name=op.f('fk_courses_subject_id_subjects'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_courses'))
    )
    op.create_index(op.f('ix_courses_subject_id'), 'courses', ['subject_id'], unique=False)
    op.create_index(op.f('ix_courses_teacher_name'), 'courses', ['teacher_name'], unique=False)

    op.create_table('course_chapters',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('course_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('video_count', sa.Integer(), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('video_count >= 0', name=op.f('ck_course_chapters_ck_course_chapters_video_count_non_negative')),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], name=op.f('fk_course_chapters_course_id_courses'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_course_chapters'))
    )
    op.create_index(op.f('ix_course_chapters_course_id'), 'course_chapters', ['course_id'], unique=False)

    op.create_table('books',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('subject_id', sa.Uuid(), nullable=False),
        sa.Column('title', sa.String(length=150), nullable=False),
        sa.Column('grade', sa.String(length=50), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], name=op.f('fk_books_subject_id_subjects'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_books'))
    )
    op.create_index(op.f('ix_books_subject_id'), 'books', ['subject_id'], unique=False)

    op.create_table('book_chapters',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('book_id', sa.Uuid(), nullable=False),
        sa.Column('title', sa.String(length=150), nullable=False),
        sa.Column('test_count', sa.Integer(), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('test_count >= 0', name=op.f('ck_book_chapters_ck_book_chapters_test_count_non_negative')),
        sa.ForeignKeyConstraint(['book_id'], ['books.id'], name=op.f('fk_book_chapters_book_id_books'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_book_chapters'))
    )
    op.create_index(op.f('ix_book_chapters_book_id'), 'book_chapters', ['book_id'], unique=False)


def downgrade() -> None:
    op.drop_table('book_chapters')
    op.drop_table('books')
    op.drop_table('course_chapters')
    op.drop_table('courses')
    op.drop_table('student_custom_subjects')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_users_academic_track_id_academic_tracks'), type_='foreignkey')
        batch_op.drop_column('is_subjects_customized')
        batch_op.drop_column('academic_track_id')
    op.drop_table('track_subjects')
    op.drop_table('academic_tracks')
    op.drop_table('subjects')

