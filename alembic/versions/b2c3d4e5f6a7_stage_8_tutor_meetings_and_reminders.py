"""stage_8_tutor_meetings_and_reminders

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-15 02:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. tutor_meetings table
    op.create_table(
        'tutor_meetings',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tutor_id', sa.Uuid(), nullable=False),
        sa.Column('student_id', sa.Uuid(), nullable=False),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=False),
        sa.Column('meeting_type', sa.String(length=20), nullable=False),
        sa.Column('meeting_url', sa.String(length=1024), nullable=True),
        sa.Column('location', sa.String(length=500), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('reminder_minutes', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tutor_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_tutor_meetings_tutor_id', 'tutor_meetings', ['tutor_id'], unique=False)
    op.create_index('ix_tutor_meetings_student_id', 'tutor_meetings', ['student_id'], unique=False)
    op.create_index('ix_tutor_meetings_start_time', 'tutor_meetings', ['start_time'], unique=False)
    op.create_index('ix_tutor_meetings_end_time', 'tutor_meetings', ['end_time'], unique=False)
    op.create_index('ix_tutor_meetings_status', 'tutor_meetings', ['status'], unique=False)

    # 2. meeting_reschedule_history table
    op.create_table(
        'meeting_reschedule_history',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('meeting_id', sa.Uuid(), nullable=False),
        sa.Column('previous_start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('previous_end_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('previous_duration_minutes', sa.Integer(), nullable=False),
        sa.Column('new_start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('new_end_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('new_duration_minutes', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['meeting_id'], ['tutor_meetings.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_meeting_reschedule_history_meeting_id', 'meeting_reschedule_history', ['meeting_id'], unique=False)
    # 3. meeting_reminders table
    op.create_table(
        'meeting_reminders',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('meeting_id', sa.Uuid(), nullable=False),
        sa.Column('tutor_id', sa.Uuid(), nullable=False),
        sa.Column('scheduled_for', sa.DateTime(timezone=True), nullable=False),
        sa.Column('triggered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_dismissed', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('dismissed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_cancelled', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['meeting_id'], ['tutor_meetings.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tutor_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_meeting_reminders_meeting_id', 'meeting_reminders', ['meeting_id'], unique=False)
    op.create_index('ix_meeting_reminders_tutor_id', 'meeting_reminders', ['tutor_id'], unique=False)
    op.create_index('ix_meeting_reminders_scheduled_for', 'meeting_reminders', ['scheduled_for'], unique=False)
    op.create_index('ix_meeting_reminders_is_dismissed', 'meeting_reminders', ['is_dismissed'], unique=False)
    op.create_index('ix_meeting_reminders_is_cancelled', 'meeting_reminders', ['is_cancelled'], unique=False)


def downgrade() -> None:
    op.drop_table('meeting_reminders')
    op.drop_table('meeting_reschedule_history')
    op.drop_table('tutor_meetings')
