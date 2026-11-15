"""stage_8b_semi_automatic_scheduler

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-15 03:20:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add notification_sent_at to tutor_meetings
    with op.batch_alter_table('tutor_meetings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('notification_sent_at', sa.DateTime(timezone=True), nullable=True))

    # 2. Create weekly_schedule_proposals
    op.create_table(
        'weekly_schedule_proposals',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tutor_id', sa.Uuid(), nullable=False),
        sa.Column('target_week_start', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tutor_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_weekly_schedule_proposals_tutor_id', 'weekly_schedule_proposals', ['tutor_id'], unique=False)
    op.create_index('ix_weekly_schedule_proposals_target_week_start', 'weekly_schedule_proposals', ['target_week_start'], unique=False)
    op.create_index('ix_weekly_schedule_proposals_status', 'weekly_schedule_proposals', ['status'], unique=False)

    # 3. Create weekly_schedule_items
    op.create_table(
        'weekly_schedule_items',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('proposal_id', sa.Uuid(), nullable=False),
        sa.Column('student_id', sa.Uuid(), nullable=False),
        sa.Column('scheduled_date', sa.Date(), nullable=False),
        sa.Column('start_time_str', sa.String(length=10), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=False),
        sa.Column('meeting_type', sa.String(length=20), nullable=False),
        sa.Column('meeting_url', sa.String(length=1024), nullable=True),
        sa.Column('location', sa.String(length=500), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('preference_source', sa.String(length=100), nullable=True),
        sa.Column('is_manually_adjusted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('meeting_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['meeting_id'], ['tutor_meetings.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['proposal_id'], ['weekly_schedule_proposals.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_weekly_schedule_items_proposal_id', 'weekly_schedule_items', ['proposal_id'], unique=False)
    op.create_index('ix_weekly_schedule_items_student_id', 'weekly_schedule_items', ['student_id'], unique=False)


def downgrade() -> None:
    op.drop_table('weekly_schedule_items')
    op.drop_table('weekly_schedule_proposals')
    with op.batch_alter_table('tutor_meetings', schema=None) as batch_op:
        batch_op.drop_column('notification_sent_at')
