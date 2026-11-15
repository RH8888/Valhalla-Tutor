"""allow_retake_practice_exams

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-11-15 05:18:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('practice_exams', schema=None) as batch_op:
        batch_op.add_column(sa.Column('allow_retake', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('practice_exams', schema=None) as batch_op:
        batch_op.drop_column('allow_retake')
