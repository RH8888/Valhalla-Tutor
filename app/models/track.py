import uuid
from datetime import datetime
from typing import List, Optional
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Table, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timezone import now_utc
from app.models.base import Base

track_subjects = Table(
    "track_subjects",
    Base.metadata,
    Column("track_id", Uuid, ForeignKey("academic_tracks.id", ondelete="CASCADE"), primary_key=True),
    Column("subject_id", Uuid, ForeignKey("subjects.id", ondelete="RESTRICT"), primary_key=True),
    Column("created_at", DateTime(timezone=True), default=now_utc, nullable=False),
)

student_custom_subjects = Table(
    "student_custom_subjects",
    Base.metadata,
    Column("student_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("subject_id", Uuid, ForeignKey("subjects.id", ondelete="RESTRICT"), primary_key=True),
    Column("created_at", DateTime(timezone=True), default=now_utc, nullable=False),
)


class AcademicTrack(Base):
    __tablename__ = "academic_tracks"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
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

    subjects: Mapped[List["Subject"]] = relationship(
        "Subject",
        secondary=track_subjects,
        order_by="Subject.name",
    )

