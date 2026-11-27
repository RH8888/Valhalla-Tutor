"""add_telegram_backup_settings

Revision ID: 3d4e5f6a7b8c
Revises: 2c3d4e5f6a7b
Create Date: 2026-11-27 15:55:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "3d4e5f6a7b8c"
down_revision: Union[str, Sequence[str], None] = "2c3d4e5f6a7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "telegram_backup_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("singleton_key", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("encrypted_bot_token", sa.Text(), nullable=True),
        sa.Column("bot_token_mask", sa.String(length=64), nullable=True),
        sa.Column("chat_id", sa.String(length=128), nullable=True),
        sa.Column("last_backup_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_backup_success", sa.Boolean(), nullable=True),
        sa.Column("last_backup_message", sa.String(length=500), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_telegram_backup_settings"),
        sa.UniqueConstraint("singleton_key", name="uq_telegram_backup_settings_singleton_key"),
    )


def downgrade() -> None:
    op.drop_table("telegram_backup_settings")
