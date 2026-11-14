"""stage_6_grades_and_actual_duration

Revision ID: b5e89a1c2d34
Revises: 9d5e31a9b201
Create Date: 2026-11-14 22:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b5e89a1c2d34'
down_revision: Union[str, Sequence[str], None] = '9d5e31a9b201'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create subject_grades table
    op.create_table(
        'subject_grades',
        sa.Column('subject_id', sa.Uuid(), nullable=False),
        sa.Column('grade', sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ['subject_id'],
            ['subjects.id'],
            name=op.f('fk_subject_grades_subject_id_subjects'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('subject_id', 'grade', name=op.f('pk_subject_grades')),
    )

    # 2. Add grade to users
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('grade', sa.String(length=20), nullable=True))
        batch_op.create_index(batch_op.f('ix_users_grade'), ['grade'], unique=False)

    # 3. Add actual_duration_minutes to plan_assignments
    with op.batch_alter_table('plan_assignments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('actual_duration_minutes', sa.Integer(), nullable=True))

    # 4. Add actual_duration_minutes to completion_audit_logs
    with op.batch_alter_table('completion_audit_logs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('actual_duration_minutes', sa.Integer(), nullable=True))

    # 5. Data migration: Initialize existing subjects with default supported grades 10, 11, 12
    conn = op.get_bind()
    try:
        subjects_res = conn.execute(sa.text("SELECT id FROM subjects")).fetchall()
        for row in subjects_res:
            subj_id = str(row[0])
            for g in ["10", "11", "12"]:
                conn.execute(
                    sa.text("INSERT INTO subject_grades (subject_id, grade) VALUES (:sid, :grade)"),
                    {"sid": subj_id, "grade": g},
                )
    except Exception:
        pass


def downgrade() -> None:
    with op.batch_alter_table('completion_audit_logs', schema=None) as batch_op:
        batch_op.drop_column('actual_duration_minutes')

    with op.batch_alter_table('plan_assignments', schema=None) as batch_op:
        batch_op.drop_column('actual_duration_minutes')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_grade'))
        batch_op.drop_column('grade')

    op.drop_table('subject_grades')

