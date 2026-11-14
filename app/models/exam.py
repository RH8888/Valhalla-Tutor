import uuid
from datetime import date, datetime
from typing import List, Optional
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timezone import now_utc
from app.models.base import Base


class Exam(Base):
    """Reusable exam definition (e.g. آزمون جامع شماره ۱)."""
    __tablename__ = "exams"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    title: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        index=True,
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
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

    sessions: Mapped[List["ExamSession"]] = relationship(
        "ExamSession",
        back_populates="exam",
        cascade="all, delete-orphan",
        order_by="desc(ExamSession.date)",
    )


class ExamSession(Base):
    """Dated occurrence of an exam."""
    __tablename__ = "exam_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    exam_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("exams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )
    title: Mapped[Optional[str]] = mapped_column(
        String(200),
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

    exam: Mapped["Exam"] = relationship("Exam", back_populates="sessions")
    track_configs: Mapped[List["ExamTrackConfiguration"]] = relationship(
        "ExamTrackConfiguration",
        back_populates="exam_session",
        cascade="all, delete-orphan",
    )
    results: Mapped[List["StudentExamResult"]] = relationship(
        "StudentExamResult",
        back_populates="exam_session",
        cascade="all, delete-orphan",
    )


class ExamTrackConfiguration(Base):
    """Tracks authorized to participate in an exam session."""
    __tablename__ = "exam_track_configurations"
    __table_args__ = (
        UniqueConstraint("exam_session_id", "track_id", name="uq_exam_track_config"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    exam_session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("exam_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    track_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("academic_tracks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
    )

    exam_session: Mapped["ExamSession"] = relationship("ExamSession", back_populates="track_configs")
    track: Mapped["AcademicTrack"] = relationship("AcademicTrack")
    subject_configs: Mapped[List["ExamSubjectConfiguration"]] = relationship(
        "ExamSubjectConfiguration",
        back_populates="track_config",
        cascade="all, delete-orphan",
    )


class ExamSubjectConfiguration(Base):
    """Subjects included in an exam for a specific track."""
    __tablename__ = "exam_subject_configurations"
    __table_args__ = (
        UniqueConstraint("exam_track_config_id", "subject_id", name="uq_exam_subject_config"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    exam_track_config_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("exam_track_configurations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("subjects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
    )

    track_config: Mapped["ExamTrackConfiguration"] = relationship("ExamTrackConfiguration", back_populates="subject_configs")
    subject: Mapped["Subject"] = relationship("Subject")


class StudentExamResult(Base):
    """Overall result submitted by a student for an exam session."""
    __tablename__ = "student_exam_results"
    __table_args__ = (
        UniqueConstraint("student_id", "exam_session_id", name="uq_student_exam_session"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    exam_session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("exam_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    overall_rank: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(
        String(500),
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

    student: Mapped["User"] = relationship("User")
    exam_session: Mapped["ExamSession"] = relationship("ExamSession", back_populates="results")
    subject_results: Mapped[List["StudentExamSubjectResult"]] = relationship(
        "StudentExamSubjectResult",
        back_populates="exam_result",
        cascade="all, delete-orphan",
    )


class StudentExamSubjectResult(Base):
    """Subject-level score entered by a student for an exam."""
    __tablename__ = "student_exam_subject_results"
    __table_args__ = (
        UniqueConstraint("student_exam_result_id", "subject_id", name="uq_result_subject"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    student_exam_result_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("student_exam_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("subjects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    correct_answers: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    incorrect_answers: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    percentage: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
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

    exam_result: Mapped["StudentExamResult"] = relationship("StudentExamResult", back_populates="subject_results")
    subject: Mapped["Subject"] = relationship("Subject")
