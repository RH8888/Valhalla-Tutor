import uuid
from datetime import datetime
from typing import List, Optional
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timezone import now_utc
from app.models.base import Base


class PracticeExam(Base):
    """Tutor-created practice exam containing complete PDF booklets."""
    __tablename__ = "practice_exams"

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
    grade: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )
    academic_track_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("academic_tracks.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    is_timed: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
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

    track: Mapped["AcademicTrack"] = relationship("AcademicTrack")
    booklets: Mapped[List["PracticeExamBooklet"]] = relationship(
        "PracticeExamBooklet",
        back_populates="practice_exam",
        cascade="all, delete-orphan",
        order_by="PracticeExamBooklet.order_index",
    )
    reporting_groups: Mapped[List["PracticeExamReportingGroup"]] = relationship(
        "PracticeExamReportingGroup",
        back_populates="practice_exam",
        cascade="all, delete-orphan",
        order_by="PracticeExamReportingGroup.title",
    )
    questions: Mapped[List["PracticeExamQuestion"]] = relationship(
        "PracticeExamQuestion",
        back_populates="practice_exam",
        cascade="all, delete-orphan",
        order_by="PracticeExamQuestion.question_number",
    )
    assignments: Mapped[List["PracticeExamAssignment"]] = relationship(
        "PracticeExamAssignment",
        back_populates="practice_exam",
        cascade="all, delete-orphan",
    )
    attempts: Mapped[List["StudentPracticeAttempt"]] = relationship(
        "StudentPracticeAttempt",
        back_populates="practice_exam",
        cascade="all, delete-orphan",
    )


class PracticeExamBooklet(Base):
    """PDF booklet within a practice exam with its own question range and duration."""
    __tablename__ = "practice_exam_booklets"
    __table_args__ = (
        UniqueConstraint("practice_exam_id", "order_index", name="uq_practice_booklet_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    practice_exam_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("practice_exams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    title: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )
    pdf_file_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    pdf_file_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    question_start: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    question_end: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    duration_minutes: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
    )

    practice_exam: Mapped["PracticeExam"] = relationship("PracticeExam", back_populates="booklets")


class PracticeExamReportingGroup(Base):
    """Subject reporting group configured for combining multiple subjects or separate reporting."""
    __tablename__ = "practice_exam_reporting_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    practice_exam_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("practice_exams.id", ondelete="CASCADE"),
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

    practice_exam: Mapped["PracticeExam"] = relationship("PracticeExam", back_populates="reporting_groups")
    questions: Mapped[List["PracticeExamQuestion"]] = relationship("PracticeExamQuestion", back_populates="reporting_group")


class PracticeExamQuestion(Base):
    """Question definition with answer key (1, 2, 3, 4), subject, and reporting group."""
    __tablename__ = "practice_exam_questions"
    __table_args__ = (
        UniqueConstraint("practice_exam_id", "question_number", name="uq_practice_question_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    practice_exam_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("practice_exams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    correct_choice: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("subjects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    reporting_group_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("practice_exam_reporting_groups.id", ondelete="SET NULL"),
        nullable=True,
    )

    practice_exam: Mapped["PracticeExam"] = relationship("PracticeExam", back_populates="questions")
    subject: Mapped["Subject"] = relationship("Subject")
    reporting_group: Mapped[Optional["PracticeExamReportingGroup"]] = relationship("PracticeExamReportingGroup", back_populates="questions")


class PracticeExamAssignment(Base):
    __tablename__ = "practice_exam_assignments"
    __table_args__ = (
        UniqueConstraint("practice_exam_id", "student_id", name="uq_practice_assignment"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    practice_exam_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("practice_exams.id", ondelete="CASCADE"),
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

    practice_exam: Mapped["PracticeExam"] = relationship("PracticeExam", back_populates="assignments")
    student: Mapped["User"] = relationship("User")


class StudentPracticeAttempt(Base):
    """Student attempt for a practice exam."""
    __tablename__ = "student_practice_attempts"

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
    practice_exam_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("practice_exams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_timed: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="IN_PROGRESS",  # "IN_PROGRESS", "COMPLETED"
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    total_correct: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    total_incorrect: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    total_unanswered: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    overall_percentage: Mapped[float] = mapped_column(
        Float,
        default=0.0,
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

    student: Mapped["User"] = relationship("User")
    practice_exam: Mapped["PracticeExam"] = relationship("PracticeExam", back_populates="attempts")
    booklet_attempts: Mapped[List["StudentPracticeBookletAttempt"]] = relationship(
        "StudentPracticeBookletAttempt",
        back_populates="attempt",
        cascade="all, delete-orphan",
        order_by="StudentPracticeBookletAttempt.started_at",
    )
    answers: Mapped[List["StudentPracticeAnswer"]] = relationship(
        "StudentPracticeAnswer",
        back_populates="attempt",
        cascade="all, delete-orphan",
    )


class StudentPracticeBookletAttempt(Base):
    """Tracks progression, timer, and server-side locking per booklet."""
    __tablename__ = "student_practice_booklet_attempts"
    __table_args__ = (
        UniqueConstraint("attempt_id", "booklet_id", name="uq_attempt_booklet"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("student_practice_attempts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    booklet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("practice_exam_booklets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_locked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    locked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    attempt: Mapped["StudentPracticeAttempt"] = relationship("StudentPracticeAttempt", back_populates="booklet_attempts")
    booklet: Mapped["PracticeExamBooklet"] = relationship("PracticeExamBooklet")


class StudentPracticeAnswer(Base):
    """Answer entered by a student for a single question."""
    __tablename__ = "student_practice_answers"
    __table_args__ = (
        UniqueConstraint("attempt_id", "question_number", name="uq_attempt_question_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("student_practice_attempts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    booklet_attempt_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("student_practice_booklet_attempts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    selected_choice: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,  # 1, 2, 3, 4, or None
    )
    is_correct: Mapped[Optional[bool]] = mapped_column(
        Boolean,
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

    attempt: Mapped["StudentPracticeAttempt"] = relationship("StudentPracticeAttempt", back_populates="answers")
    booklet_attempt: Mapped["StudentPracticeBookletAttempt"] = relationship("StudentPracticeBookletAttempt")
