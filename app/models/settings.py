from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.models.base import Base


class TelegramBackupSettings(Base):
    """Singleton configuration and status for off-site Telegram backup delivery."""

    __tablename__ = "telegram_backup_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    singleton_key: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        nullable=False,
        default="default",
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    encrypted_bot_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bot_token_mask: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    chat_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    last_backup_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_backup_success: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    last_backup_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
        onupdate=now_utc,
    )
