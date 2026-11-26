"""restrict_completion_audit_assignment_delete

Revision ID: 2c3d4e5f6a7b
Revises: 1b2c3d4e5f6a
Create Date: 2026-11-26 02:41:00.000000

"""
from typing import Sequence, Union
from alembic import op

revision: str = "2c3d4e5f6a7b"
down_revision: Union[str, Sequence[str], None] = "1b2c3d4e5f6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("completion_audit_logs", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_completion_audit_logs_assignment_id_plan_assignments",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_completion_audit_logs_assignment_id_plan_assignments",
            "plan_assignments",
            ["assignment_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("completion_audit_logs", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_completion_audit_logs_assignment_id_plan_assignments",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_completion_audit_logs_assignment_id_plan_assignments",
            "plan_assignments",
            ["assignment_id"],
            ["id"],
            ondelete="CASCADE",
        )
