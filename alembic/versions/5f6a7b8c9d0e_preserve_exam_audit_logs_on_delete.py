"""preserve_exam_audit_logs_on_delete

Revision ID: 5f6a7b8c9d0e
Revises: 4e5f6a7b8c9d
Create Date: 2026-11-27 23:55:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "5f6a7b8c9d0e"
down_revision: Union[str, Sequence[str], None] = "4e5f6a7b8c9d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("exam_audit_logs", schema=None) as batch_op:
        batch_op.alter_column("exam_id", existing_type=sa.Uuid(), nullable=True)
        batch_op.drop_constraint(
            "fk_exam_audit_logs_exam_id_exams",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_exam_audit_logs_exam_id_exams",
            "exams",
            ["exam_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("exam_audit_logs", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_exam_audit_logs_exam_id_exams",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_exam_audit_logs_exam_id_exams",
            "exams",
            ["exam_id"],
            ["id"],
            ondelete="CASCADE",
        )
