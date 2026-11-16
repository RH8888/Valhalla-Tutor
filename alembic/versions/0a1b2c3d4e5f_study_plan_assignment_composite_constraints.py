"""study_plan_assignment_composite_constraints

Revision ID: 0a1b2c3d4e5f
Revises: f6a7b8c9d0e1
Create Date: 2026-11-17 00:20:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0a1b2c3d4e5f'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Inspect existing database records for duplicate (id, student_id) in study_plans
    dup_plans = bind.execute(sa.text("""
        SELECT id, student_id, COUNT(*) as cnt
        FROM study_plans
        GROUP BY id, student_id
        HAVING COUNT(*) > 1
    """)).fetchall()
    if dup_plans:
        raise RuntimeError(
            f"Cannot apply uq_study_plans_id_student: duplicate records found in study_plans: {dup_plans}"
        )

    # 2. Inspect existing database records for mismatched student_id between plan_assignments and study_plans
    mismatched = bind.execute(sa.text("""
        SELECT pa.id AS assignment_id, pa.study_plan_id, pa.student_id AS assignment_student_id, sp.student_id AS plan_student_id
        FROM plan_assignments pa
        JOIN study_plans sp ON pa.study_plan_id = sp.id
        WHERE pa.student_id != sp.student_id
    """)).fetchall()
    if mismatched:
        raise RuntimeError(
            f"Cannot apply composite foreign key: found plan_assignments with student_id different from study_plan.student_id: {mismatched}"
        )

    # 3. Inspect existing database records for orphaned plan_assignments
    orphaned = bind.execute(sa.text("""
        SELECT pa.id AS assignment_id, pa.study_plan_id, pa.student_id
        FROM plan_assignments pa
        LEFT JOIN study_plans sp ON pa.study_plan_id = sp.id
        WHERE sp.id IS NULL
    """)).fetchall()
    if orphaned:
        raise RuntimeError(
            f"Cannot apply composite foreign key: found orphaned plan_assignments referencing non-existent study_plans: {orphaned}"
        )

    # 4. Add composite unique constraint on study_plans(id, student_id)
    with op.batch_alter_table('study_plans', schema=None) as batch_op:
        batch_op.create_unique_constraint(
            'uq_study_plans_id_student',
            ['id', 'student_id']
        )

    # 5. Add composite foreign key on plan_assignments(study_plan_id, student_id) -> study_plans(id, student_id)
    with op.batch_alter_table('plan_assignments', schema=None) as batch_op:
        batch_op.create_foreign_key(
            'fk_plan_assignments_study_plan_student',
            'study_plans',
            ['study_plan_id', 'student_id'],
            ['id', 'student_id'],
            ondelete='CASCADE'
        )


def downgrade() -> None:
    with op.batch_alter_table('plan_assignments', schema=None) as batch_op:
        batch_op.drop_constraint('fk_plan_assignments_study_plan_student', type_='foreignkey')

    with op.batch_alter_table('study_plans', schema=None) as batch_op:
        batch_op.drop_constraint('uq_study_plans_id_student', type_='unique')
