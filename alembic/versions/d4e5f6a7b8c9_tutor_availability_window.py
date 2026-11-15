"""tutor_availability_window

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-11-15 04:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('weekly_schedule_proposals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('avail_start_time_str', sa.String(length=10), server_default='09:00', nullable=True))
        batch_op.add_column(sa.Column('avail_end_time_str', sa.String(length=10), server_default='21:00', nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('weekly_schedule_proposals', schema=None) as batch_op:
        batch_op.drop_column('avail_end_time_str')
        batch_op.drop_column('avail_start_time_str')
