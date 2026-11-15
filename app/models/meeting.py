import enum
import uuid
from datetime import date, datetime, time
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, Time, Uuid
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
    notification_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
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


class ProposalStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    DISCARDED = "DISCARDED"


class WeeklyScheduleProposal(Base):
    __tablename__ = "weekly_schedule_proposals"

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
    target_week_start: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )
    status: Mapped[ProposalStatus] = mapped_column(
        String(20),
        nullable=False,
        default=ProposalStatus.DRAFT,
        index=True,
    )
    avail_start_time_str: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        default="09:00",
    )
    avail_end_time_str: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        default="21:00",
    )
    daily_availability_json: Mapped[Optional[str]] = mapped_column(
        Text,
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

    def get_daily_availability(self) -> dict:
        """Return dict of day-by-day availability settings."""
        import json
        if self.daily_availability_json:
            try:
                data = json.loads(self.daily_availability_json)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        s_time = self.avail_start_time_str or "14:00"
        e_time = self.avail_end_time_str or "21:00"
        days = ["saturday", "sunday", "monday", "tuesday", "wednesday", "thursday", "friday"]
        return {
            d: {
                "is_available": True,
                "start_time": s_time,
                "end_time": e_time,
                "mode": "custom",
            }
            for d in days
        }

    tutor: Mapped["User"] = relationship(
        "User",
        foreign_keys=[tutor_id],
    )
    items: Mapped[List["WeeklyScheduleItem"]] = relationship(
        "WeeklyScheduleItem",
        back_populates="proposal",
        cascade="all, delete-orphan",
        order_by="WeeklyScheduleItem.scheduled_date.asc(), WeeklyScheduleItem.start_time_str.asc()",
    )


class WeeklyScheduleItem(Base):
    __tablename__ = "weekly_schedule_items"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("weekly_schedule_proposals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scheduled_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    start_time_str: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )
    duration_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=60,
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
    preference_source: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    is_manually_adjusted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    meeting_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("tutor_meetings.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
    )

    proposal: Mapped["WeeklyScheduleProposal"] = relationship(
        "WeeklyScheduleProposal",
        back_populates="items",
    )
    student: Mapped["User"] = relationship(
        "User",
        foreign_keys=[student_id],
    )
    meeting: Mapped[Optional["TutorMeeting"]] = relationship(
        "TutorMeeting",
        foreign_keys=[meeting_id],
    )
