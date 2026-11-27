"""add_telegram_backup_schedule

Revision ID: 4e5f6a7b8c9d
Revises: 3d4e5f6a7b8c
Create Date: 2026-11-27 18:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "4e5f6a7b8c9d"
down_revision: Union[str, Sequence[str], None] = "3d4e5f6a7b8c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "telegram_backup_settings",
        sa.Column("schedule_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "telegram_backup_settings",
        sa.Column("schedule_mode", sa.String(length=16), nullable=False, server_default="daily"),
    )
    op.add_column(
        "telegram_backup_settings",
        sa.Column("interval_value", sa.Integer(), nullable=False, server_default="24"),
    )
    op.add_column(
        "telegram_backup_settings",
        sa.Column("interval_unit", sa.String(length=16), nullable=False, server_default="hours"),
    )
    op.add_column(
        "telegram_backup_settings",
        sa.Column("daily_time", sa.String(length=5), nullable=False, server_default="00:00"),
    )
    op.add_column(
        "telegram_backup_settings",
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("telegram_backup_settings", "next_run_at")
    op.drop_column("telegram_backup_settings", "daily_time")
    op.drop_column("telegram_backup_settings", "interval_unit")
    op.drop_column("telegram_backup_settings", "interval_value")
    op.drop_column("telegram_backup_settings", "schedule_mode")
    op.drop_column("telegram_backup_settings", "schedule_enabled")
