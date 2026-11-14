import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timezone import now_utc
from app.models.base import Base
from app.models.track import student_custom_subjects

if TYPE_CHECKING:
    from app.models.session import UserSession
    from app.models.track import AcademicTrack
    from app.models.subject import Subject


class UserRole(str, enum.Enum):
    TUTOR = "TUTOR"
    STUDENT = "STUDENT"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    username: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
    )
    email: Mapped[Optional[str]] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    role: Mapped[UserRole] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        default=UserRole.STUDENT,
    )
    full_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    timezone: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="Asia/Tehran",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    academic_track_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("academic_tracks.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_subjects_customized: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    grade: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
        onupdate=now_utc,
    )

    sessions: Mapped[List["UserSession"]] = relationship(
        "UserSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    academic_track: Mapped[Optional["AcademicTrack"]] = relationship(
        "AcademicTrack",
        foreign_keys=[academic_track_id],
    )
    custom_subjects: Mapped[List["Subject"]] = relationship(
        "Subject",
        secondary=student_custom_subjects,
        order_by="Subject.name",
    )

