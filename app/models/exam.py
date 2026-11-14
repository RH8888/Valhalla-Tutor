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
    grade: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        index=True,
    )
    submission_deadline: Mapped[Optional[datetime]] = mapped_column(
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
    assignments: Mapped[List["ExternalExamAssignment"]] = relationship(
        "ExternalExamAssignment",
        back_populates="exam_session",
        cascade="all, delete-orphan",
    )
    reporting_groups: Mapped[List["ExamReportingGroup"]] = relationship(
        "ExamReportingGroup",
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
    report_card_file_path: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    report_card_file_name: Mapped[Optional[str]] = mapped_column(
        String(255),
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


class ExternalExamAssignment(Base):
    """Assigns a scheduled external exam session to a specific student."""
    __tablename__ = "external_exam_assignments"
    __table_args__ = (
        UniqueConstraint("exam_session_id", "student_id", name="uq_external_exam_assignment"),
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
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
    )

    exam_session: Mapped["ExamSession"] = relationship("ExamSession", back_populates="assignments")
    student: Mapped["User"] = relationship("User")


class ExamReportingGroup(Base):
    """Flexible reporting group for external exams (e.g. Mathematics combining Geometry, Calculus, Stats)."""
    __tablename__ = "exam_reporting_groups"

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
    title: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
    )

    exam_session: Mapped["ExamSession"] = relationship("ExamSession", back_populates="reporting_groups")
    subjects: Mapped[List["Subject"]] = relationship(
        "Subject",
        secondary="exam_reporting_group_subjects",
        order_by="Subject.name",
    )


class ExamReportingGroupSubject(Base):
    __tablename__ = "exam_reporting_group_subjects"

    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("exam_reporting_groups.id", ondelete="CASCADE"),
        primary_key=True,
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("subjects.id", ondelete="CASCADE"),
        primary_key=True,
    )


class HistoricalExamResult(Base):
    """Manually recorded historical results not linked to an active scheduled exam session."""
    __tablename__ = "historical_exam_results"

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
    exam_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        index=True,
    )
    exam_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )
    grade: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
    )
    academic_track_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("academic_tracks.id", ondelete="SET NULL"),
        nullable=True,
    )
    overall_rank: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    report_card_file_path: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    report_card_file_name: Mapped[Optional[str]] = mapped_column(
        String(255),
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
    academic_track: Mapped[Optional["AcademicTrack"]] = relationship("AcademicTrack")
    subject_results: Mapped[List["HistoricalExamSubjectResult"]] = relationship(
        "HistoricalExamSubjectResult",
        back_populates="historical_result",
        cascade="all, delete-orphan",
    )


class HistoricalExamSubjectResult(Base):
    __tablename__ = "historical_exam_subject_results"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    historical_exam_result_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("historical_exam_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    percentage: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
    )

    historical_result: Mapped["HistoricalExamResult"] = relationship("HistoricalExamResult", back_populates="subject_results")
