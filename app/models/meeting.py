import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timezone import now_utc
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class MeetingType(str, enum.Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class MeetingStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    STUDENT_ABSENT = "STUDENT_ABSENT"


class TutorMeeting(Base):
    __tablename__ = "tutor_meetings"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    tutor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    end_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    duration_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    meeting_type: Mapped[MeetingType] = mapped_column(
        String(20),
        nullable=False,
        default=MeetingType.ONLINE,
    )
    meeting_url: Mapped[Optional[str]] = mapped_column(
        String(1024),
        nullable=True,
    )
    location: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    status: Mapped[MeetingStatus] = mapped_column(
        String(30),
        nullable=False,
        default=MeetingStatus.SCHEDULED,
        index=True,
    )
    reminder_minutes: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
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

    tutor: Mapped["User"] = relationship(
        "User",
        foreign_keys=[tutor_id],
    )
    student: Mapped["User"] = relationship(
        "User",
        foreign_keys=[student_id],
    )
    reschedule_history: Mapped[List["MeetingRescheduleHistory"]] = relationship(
        "MeetingRescheduleHistory",
        back_populates="meeting",
        cascade="all, delete-orphan",
        order_by="MeetingRescheduleHistory.created_at.desc()",
    )
    reminders: Mapped[List["MeetingReminder"]] = relationship(
        "MeetingReminder",
        back_populates="meeting",
        cascade="all, delete-orphan",
        order_by="MeetingReminder.created_at.desc()",
    )


class MeetingRescheduleHistory(Base):
    __tablename__ = "meeting_reschedule_history"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("tutor_meetings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    previous_start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    previous_end_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    previous_duration_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    new_start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    new_end_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    new_duration_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    reason: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
    )

    meeting: Mapped["TutorMeeting"] = relationship(
        "TutorMeeting",
        back_populates="reschedule_history",
    )


class MeetingReminder(Base):
    __tablename__ = "meeting_reminders"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("tutor_meetings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tutor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    triggered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_dismissed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_cancelled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
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

    meeting: Mapped["TutorMeeting"] = relationship(
        "TutorMeeting",
        back_populates="reminders",
    )
    tutor: Mapped["User"] = relationship(
        "User",
        foreign_keys=[tutor_id],
    )
