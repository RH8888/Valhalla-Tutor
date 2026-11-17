"""unique_published_study_plan_per_student

Revision ID: 1b2c3d4e5f6a
Revises: 0a1b2c3d4e5f
Create Date: 2026-11-17 21:15:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '1b2c3d4e5f6a'
down_revision: Union[str, Sequence[str], None] = '0a1b2c3d4e5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Check existing records for conflicting multiple PUBLISHED plans per student
    conflicting = bind.execute(sa.text("""
        SELECT student_id, COUNT(*) as cnt
        FROM study_plans
        WHERE status = 'PUBLISHED'
        GROUP BY student_id
        HAVING COUNT(*) > 1
    """)).fetchall()
    if conflicting:
        raise RuntimeError(
            f"Cannot create partial unique index uq_study_plans_student_published: multiple published study plans found for student(s): {conflicting}"
        )

    # 2. Add partial unique index on student_id where status = 'PUBLISHED'
    op.create_index(
        'uq_study_plans_student_published',
        'study_plans',
        ['student_id'],
        unique=True,
        postgresql_where=sa.text("status = 'PUBLISHED'"),
        sqlite_where=sa.text("status = 'PUBLISHED'"),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_study_plans_student_published',
        table_name='study_plans',
        postgresql_where=sa.text("status = 'PUBLISHED'"),
        sqlite_where=sa.text("status = 'PUBLISHED'"),
    )
