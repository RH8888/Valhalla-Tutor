import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timezone import now_utc
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.book import Book, BookChapter
    from app.models.course import Course, CourseChapter
    from app.models.subject import Subject
    from app.models.user import User


class PlanStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class TaskType(str, enum.Enum):
    VIDEO = "VIDEO"
    TEST = "TEST"
    CUSTOM = "CUSTOM"


class StudyPlan(Base):
    __tablename__ = "study_plans"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_study_plans_date_range"),
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
    tutor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    title: Mapped[Optional[str]] = mapped_column(
        String(150),
        nullable=True,
    )
    start_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )
    end_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    status: Mapped[PlanStatus] = mapped_column(
        String(20),
        nullable=False,
        default=PlanStatus.DRAFT,
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

    student: Mapped["User"] = relationship("User", foreign_keys=[student_id])
    tutor: Mapped["User"] = relationship("User", foreign_keys=[tutor_id])
    assignments: Mapped[List["PlanAssignment"]] = relationship(
        "PlanAssignment",
        back_populates="study_plan",
        cascade="all, delete-orphan",
        order_by="PlanAssignment.scheduled_date, PlanAssignment.display_order",
    )


class PlanAssignment(Base):
    __tablename__ = "plan_assignments"
    __table_args__ = (
        CheckConstraint("recommended_duration_minutes >= 0", name="ck_plan_assignments_duration_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    study_plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("study_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("subjects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    task_type: Mapped[TaskType] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )
    scheduled_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )
    display_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    recommended_duration_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    estimated_duration_minutes: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    is_estimated: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
    )

    # Video assignment fields
    course_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("courses.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    course_chapter_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("course_chapters.id", ondelete="SET NULL"),
        nullable=True,
    )
    video_start_num: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    video_end_num: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    video_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    course_name_snapshot: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    course_chapter_name_snapshot: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # Book assignment fields
    book_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("books.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    book_chapter_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("book_chapters.id", ondelete="SET NULL"),
        nullable=True,
    )
    test_start_num: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    test_end_num: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    test_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    book_title_snapshot: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    book_chapter_title_snapshot: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # Completion fields
    is_completed: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
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

    study_plan: Mapped["StudyPlan"] = relationship("StudyPlan", back_populates="assignments")
    student: Mapped["User"] = relationship("User", foreign_keys=[student_id])
    subject: Mapped["Subject"] = relationship("Subject", foreign_keys=[subject_id])
    course: Mapped[Optional["Course"]] = relationship("Course", foreign_keys=[course_id])
    course_chapter: Mapped[Optional["CourseChapter"]] = relationship("CourseChapter", foreign_keys=[course_chapter_id])
    book: Mapped[Optional["Book"]] = relationship("Book", foreign_keys=[book_id])
    book_chapter: Mapped[Optional["BookChapter"]] = relationship("BookChapter", foreign_keys=[book_chapter_id])
    completion_audits: Mapped[List["CompletionAuditLog"]] = relationship(
        "CompletionAuditLog",
        back_populates="assignment",
        cascade="all, delete-orphan",
        order_by="desc(CompletionAuditLog.created_at)",
    )


class CompletionAuditAction(str, enum.Enum):
    COMPLETED = "COMPLETED"
    RESET = "RESET"


class CompletionAuditLog(Base):
    __tablename__ = "completion_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("plan_assignments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    performed_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )
    recorded_completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    note: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
        index=True,
    )

    assignment: Mapped["PlanAssignment"] = relationship("PlanAssignment", back_populates="completion_audits")
    student: Mapped["User"] = relationship("User", foreign_keys=[student_id])
    performed_by: Mapped["User"] = relationship("User", foreign_keys=[performed_by_id])

