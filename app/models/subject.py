import uuid
from datetime import datetime
from typing import List, Optional
from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timezone import now_utc
from app.models.base import Base


class SubjectGrade(Base):
    __tablename__ = "subject_grades"

    subject_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("subjects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    grade: Mapped[str] = mapped_column(
        String(20),
        primary_key=True,
    )

    subject: Mapped["Subject"] = relationship("Subject", back_populates="grades_rel")


class Subject(Base):
    __tablename__ = "subjects"

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

    grades_rel: Mapped[List["SubjectGrade"]] = relationship(
        "SubjectGrade",
        back_populates="subject",
        cascade="all, delete-orphan",
        order_by="SubjectGrade.grade",
    )

    @property
    def grades(self) -> List[str]:
        return [sg.grade for sg in self.grades_rel]

