import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, joinedload

from app.core.timezone import now_utc, today_local
from app.models.book import Book, BookChapter
from app.models.course import Course, CourseChapter
from app.models.plan import CompletionAuditAction, CompletionAuditLog, PlanAssignment, PlanStatus, StudyPlan, TaskType
from app.models.subject import Subject
from app.models.user import User, UserRole
from app.services.academic_service import get_student_effective_subjects
from app.services.resource_service import normalize_grade


class PlanNotFoundError(Exception):
    pass


class AssignmentNotFoundError(Exception):
    pass


class PlanValidationError(Exception):
    pass


@dataclass
class DurationEstimate:
    suggested_duration_minutes: Optional[int]
    average_unit_minutes: Optional[float]
    unit_label: str  # "test" or "video"
    is_historical: bool
    basis_text: str
    sample_count: int
    plans_count: int


def format_duration_minutes(minutes: int) -> str:
    """Format minutes into human-readable string (e.g., '45 minutes', '2 hours', '3 hours 30 minutes')."""
    if minutes <= 0:
        return "0 minutes"
    hours = minutes // 60
    mins = minutes % 60
    if hours == 0:
        return f"{mins} minutes"
    hr_str = "1 hour" if hours == 1 else f"{hours} hours"
    if mins == 0:
        return hr_str
    return f"{hr_str} {mins} minutes"


def calculate_plan_totals(
    assignments: List[PlanAssignment],
    days: List[date],
    subjects: List[Subject],
) -> Tuple[Dict[date, int], Dict[uuid.UUID, int], int]:
    """Calculate daily totals, subject totals, and overall plan total in minutes."""
    daily_totals: Dict[date, int] = {d: 0 for d in days}
    subject_totals: Dict[uuid.UUID, int] = {s.id: 0 for s in subjects}
    plan_total = 0

    for a in assignments:
        dur = a.recommended_duration_minutes or 0
        if a.scheduled_date in daily_totals:
            daily_totals[a.scheduled_date] += dur
        if a.subject_id in subject_totals:
            subject_totals[a.subject_id] += dur
        plan_total += dur

    return daily_totals, subject_totals, plan_total


def estimate_test_duration(
    db: Session,
    student_id: uuid.UUID,
    book_id: uuid.UUID,
    test_count: int,
    tutor_id: Optional[uuid.UUID] = None,
) -> DurationEstimate:
    """
    Estimate test duration using rolling average from the student's last completed plans.
    Does not mix different books.
    """
    if test_count <= 0:
        return DurationEstimate(
            suggested_duration_minutes=None,
            average_unit_minutes=None,
            unit_label="test",
            is_historical=False,
            basis_text="Invalid test count for estimation.",
            sample_count=0,
            plans_count=0,
        )

    # Find distinct study plans containing completed assignments for this student and book
    plan_query = (
        db.query(PlanAssignment.study_plan_id)
        .join(StudyPlan, PlanAssignment.study_plan_id == StudyPlan.id)
        .filter(
            PlanAssignment.student_id == student_id,
            PlanAssignment.book_id == book_id,
            PlanAssignment.task_type == TaskType.TEST,
            PlanAssignment.is_completed.is_(True),
            PlanAssignment.test_count.isnot(None),
            PlanAssignment.test_count > 0,
            PlanAssignment.recommended_duration_minutes > 0,
        )
    )
    if tutor_id is not None:
        plan_query = plan_query.filter(StudyPlan.tutor_id == tutor_id)

    plan_subq = (
        plan_query
        .group_by(StudyPlan.id, StudyPlan.end_date, PlanAssignment.study_plan_id)
        .order_by(desc(StudyPlan.end_date))
        .limit(3)
        .subquery()
    )

    recent_plan_ids = [r[0] for r in db.query(plan_subq.c.study_plan_id).all()]
    if not recent_plan_ids:
        return DurationEstimate(
            suggested_duration_minutes=None,
            average_unit_minutes=None,
            unit_label="test",
            is_historical=False,
            basis_text="No completed tests found for this book; enter duration manually.",
            sample_count=0,
            plans_count=0,
        )

    # Aggregate historical totals from the selected plans
    query = db.query(
        func.sum(PlanAssignment.test_count),
        func.sum(PlanAssignment.recommended_duration_minutes),
        func.count(func.distinct(PlanAssignment.study_plan_id)),
    ).filter(
        PlanAssignment.student_id == student_id,
        PlanAssignment.book_id == book_id,
        PlanAssignment.study_plan_id.in_(recent_plan_ids),
        PlanAssignment.is_completed.is_(True),
        PlanAssignment.test_count.isnot(None),
        PlanAssignment.test_count > 0,
        PlanAssignment.recommended_duration_minutes > 0,
    )
    total_tests, total_minutes, plans_count = query.first()

    if not total_tests or total_tests <= 0 or not total_minutes:
        return DurationEstimate(
            suggested_duration_minutes=None,
            average_unit_minutes=None,
            unit_label="test",
            is_historical=False,
            basis_text="Insufficient completed history; enter duration manually.",
            sample_count=0,
            plans_count=0,
        )

    avg_unit_min = float(total_minutes) / float(total_tests)
    suggested = max(1, round(test_count * avg_unit_min))
    return DurationEstimate(
        suggested_duration_minutes=suggested,
        average_unit_minutes=round(avg_unit_min, 2),
        unit_label="test",
        is_historical=True,
        basis_text=f"Estimated based on historical average of {avg_unit_min:.1f} min/test ({total_tests} tests across {plans_count} plan(s)).",
        sample_count=int(total_tests),
        plans_count=int(plans_count),
    )


def estimate_video_duration(
    db: Session,
    student_id: uuid.UUID,
    course_id: uuid.UUID,
    video_count: int,
    tutor_id: Optional[uuid.UUID] = None,
) -> DurationEstimate:
    """
    Estimate video duration using rolling average from the student's last completed plans.
    Does not mix different courses.
    """
    if video_count <= 0:
        return DurationEstimate(
            suggested_duration_minutes=None,
            average_unit_minutes=None,
            unit_label="video",
            is_historical=False,
            basis_text="Invalid video count for estimation.",
            sample_count=0,
            plans_count=0,
        )

    # Find distinct study plans containing completed video assignments for this student and course
    plan_query = (
        db.query(PlanAssignment.study_plan_id)
        .join(StudyPlan, PlanAssignment.study_plan_id == StudyPlan.id)
        .filter(
            PlanAssignment.student_id == student_id,
            PlanAssignment.course_id == course_id,
            PlanAssignment.task_type == TaskType.VIDEO,
            PlanAssignment.is_completed.is_(True),
            PlanAssignment.video_count.isnot(None),
            PlanAssignment.video_count > 0,
            PlanAssignment.recommended_duration_minutes > 0,
        )
    )
    if tutor_id is not None:
        plan_query = plan_query.filter(StudyPlan.tutor_id == tutor_id)

    plan_subq = (
        plan_query
        .group_by(StudyPlan.id, StudyPlan.end_date, PlanAssignment.study_plan_id)
        .order_by(desc(StudyPlan.end_date))
        .limit(3)
        .subquery()
    )

    recent_plan_ids = [r[0] for r in db.query(plan_subq.c.study_plan_id).all()]
    if not recent_plan_ids:
        return DurationEstimate(
            suggested_duration_minutes=None,
            average_unit_minutes=None,
            unit_label="video",
            is_historical=False,
            basis_text="No completed videos found for this course; enter duration manually.",
            sample_count=0,
            plans_count=0,
        )

    query = db.query(
        func.sum(PlanAssignment.video_count),
        func.sum(PlanAssignment.recommended_duration_minutes),
        func.count(func.distinct(PlanAssignment.study_plan_id)),
    ).filter(
        PlanAssignment.student_id == student_id,
        PlanAssignment.course_id == course_id,
        PlanAssignment.study_plan_id.in_(recent_plan_ids),
        PlanAssignment.is_completed.is_(True),
        PlanAssignment.video_count.isnot(None),
        PlanAssignment.video_count > 0,
        PlanAssignment.recommended_duration_minutes > 0,
    )
    total_videos, total_minutes, plans_count = query.first()

    if not total_videos or total_videos <= 0 or not total_minutes:
        return DurationEstimate(
            suggested_duration_minutes=None,
            average_unit_minutes=None,
            unit_label="video",
            is_historical=False,
            basis_text="Insufficient completed history; enter duration manually.",
            sample_count=0,
            plans_count=0,
        )

    avg_unit_min = float(total_minutes) / float(total_videos)
    suggested = max(1, round(video_count * avg_unit_min))
    return DurationEstimate(
        suggested_duration_minutes=suggested,
        average_unit_minutes=round(avg_unit_min, 2),
        unit_label="video",
        is_historical=True,
        basis_text=f"Estimated based on historical average of {avg_unit_min:.1f} min/video ({total_videos} videos across {plans_count} plan(s)).",
        sample_count=int(total_videos),
        plans_count=int(plans_count),
    )


def create_study_plan(
    db: Session,
    student_id: uuid.UUID,
    tutor_id: uuid.UUID,
    start_date: date,
    title: Optional[str] = None,
) -> StudyPlan:
    """Create a new 14-day study plan in DRAFT status."""
    student = db.query(User).filter(User.id == student_id, User.role == UserRole.STUDENT).first()
    if not student:
        raise ValueError(f"Student with id {student_id} not found.")

    end_date = start_date + timedelta(days=13)
    clean_title = title.strip() if title else f"14-Day Plan ({start_date.isoformat()} to {end_date.isoformat()})"

    plan = StudyPlan(
        student_id=student_id,
        tutor_id=tutor_id,
        title=clean_title,
        start_date=start_date,
        end_date=end_date,
        status=PlanStatus.DRAFT,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def _lock_study_plan_row(
    db: Session,
    plan_id: uuid.UUID,
    share: bool = False,
) -> Optional[uuid.UUID]:
    row = (
        db.query(StudyPlan.id)
        .filter(StudyPlan.id == plan_id)
        .with_for_update(read=share)
        .first()
    )
    return row[0] if row else None


def _lock_assignment_with_plan(
    db: Session,
    assignment_id: uuid.UUID,
    share_plan: bool = True,
) -> Optional[PlanAssignment]:
    """Acquire hierarchical row locks (StudyPlan -> PlanAssignment) and refresh ORM state."""
    plan_row = (
        db.query(PlanAssignment.study_plan_id)
        .filter(PlanAssignment.id == assignment_id)
        .first()
    )
    if not plan_row:
        return None
    _lock_study_plan_row(db, plan_row[0], share=share_plan)
    locked_row = (
        db.query(PlanAssignment.id)
        .filter(PlanAssignment.id == assignment_id)
        .with_for_update()
        .first()
    )
    if not locked_row:
        return None
    return (
        db.query(PlanAssignment)
        .populate_existing()
        .options(joinedload(PlanAssignment.study_plan))
        .filter(PlanAssignment.id == assignment_id)
        .first()
    )


def get_study_plan(
    db: Session,
    plan_id: uuid.UUID,
    tutor_id: Optional[uuid.UUID] = None,
    student_id: Optional[uuid.UUID] = None,
    exclude_drafts: bool = False,
    populate_existing: bool = False,
) -> Optional[StudyPlan]:
    query = db.query(StudyPlan)
    if populate_existing:
        query = query.populate_existing()
    query = query.filter(StudyPlan.id == plan_id)
    if tutor_id is not None:
        query = query.filter(StudyPlan.tutor_id == tutor_id)
    if student_id is not None:
        query = query.filter(StudyPlan.student_id == student_id)
    if exclude_drafts:
        query = query.filter(StudyPlan.status != PlanStatus.DRAFT)
    return query.first()


def list_student_plans(
    db: Session,
    student_id: uuid.UUID,
    tutor_id: Optional[uuid.UUID] = None,
    exclude_drafts: bool = False,
) -> List[StudyPlan]:
    query = db.query(StudyPlan).filter(StudyPlan.student_id == student_id)
    if tutor_id is not None:
        query = query.filter(StudyPlan.tutor_id == tutor_id)
    if exclude_drafts:
        query = query.filter(StudyPlan.status != PlanStatus.DRAFT)
    return (
        query
        .order_by(desc(StudyPlan.start_date), desc(StudyPlan.created_at))
        .all()
    )


def get_active_student_plan(
    db: Session,
    student_id: uuid.UUID,
    tutor_id: Optional[uuid.UUID] = None,
) -> Optional[StudyPlan]:
    """Retrieve the single active published plan for a student, if any."""
    query = db.query(StudyPlan).filter(
        StudyPlan.student_id == student_id,
        StudyPlan.status == PlanStatus.PUBLISHED,
    )
    if tutor_id is not None:
        query = query.filter(StudyPlan.tutor_id == tutor_id)
    return query.first()


def publish_study_plan(db: Session, plan_id: uuid.UUID, tutor_id: Optional[uuid.UUID] = None) -> StudyPlan:
    """Publish a draft plan and safely archive any previously published plan for this student."""
    if not _lock_study_plan_row(db, plan_id, share=True):
        raise PlanNotFoundError(f"Plan with id {plan_id} not found.")
    plan = get_study_plan(db, plan_id, tutor_id=tutor_id, populate_existing=True)
    if not plan:
        raise PlanNotFoundError(f"Plan with id {plan_id} not found.")

    # Serialize concurrent publication requests for this student by acquiring an exclusive row lock on the student
    db.query(User).filter(User.id == plan.student_id).with_for_update().first()

    # Refresh plan state in case it was modified while waiting for the lock
    db.refresh(plan)

    if plan.status == PlanStatus.ARCHIVED:
        raise PlanValidationError("Cannot publish an archived study plan. Archived plans cannot be reactivated.")
    if plan.status != PlanStatus.DRAFT:
        raise PlanValidationError(f"Cannot publish a study plan with status '{plan.status}'. Only DRAFT plans can be published.")

    # Archive any existing published plan for the student across all tutors
    existing_published = (
        db.query(StudyPlan)
        .filter(
            StudyPlan.student_id == plan.student_id,
            StudyPlan.status == PlanStatus.PUBLISHED,
            StudyPlan.id != plan_id,
        )
        .with_for_update()
        .all()
    )
    for p in existing_published:
        p.status = PlanStatus.ARCHIVED
    # Flush archival updates before publishing the new plan so partial unique index uq_study_plans_student_published is not violated
    if existing_published:
        db.flush()

    plan.status = PlanStatus.PUBLISHED
    db.commit()
    db.refresh(plan)
    return plan


def archive_study_plan(db: Session, plan_id: uuid.UUID, tutor_id: Optional[uuid.UUID] = None) -> StudyPlan:
    if not _lock_study_plan_row(db, plan_id):
        raise PlanNotFoundError(f"Plan with id {plan_id} not found.")
    plan = get_study_plan(db, plan_id, tutor_id=tutor_id, populate_existing=True)
    if not plan:
        raise PlanNotFoundError(f"Plan with id {plan_id} not found.")
    plan.status = PlanStatus.ARCHIVED
    db.commit()
    db.refresh(plan)
    return plan


def delete_study_plan(db: Session, plan_id: uuid.UUID, tutor_id: Optional[uuid.UUID] = None) -> None:
    if not _lock_study_plan_row(db, plan_id):
        raise PlanNotFoundError(f"Plan with id {plan_id} not found.")
    plan = get_study_plan(db, plan_id, tutor_id=tutor_id, populate_existing=True)
    if not plan:
        raise PlanNotFoundError(f"Plan with id {plan_id} not found.")
    if plan.status != PlanStatus.DRAFT:
        raise PlanValidationError("Only DRAFT study plans can be deleted. Published plans must be archived.")
    has_audit_history = (
        db.query(CompletionAuditLog.id)
        .join(PlanAssignment, CompletionAuditLog.assignment_id == PlanAssignment.id)
        .filter(PlanAssignment.study_plan_id == plan.id)
        .first()
    )
    if has_audit_history:
        raise PlanValidationError("Cannot delete a study plan that has completion audit history.")
    db.delete(plan)
    db.commit()


def create_assignment(
    db: Session,
    plan_id: uuid.UUID,
    scheduled_date: date,
    subject_id: uuid.UUID,
    task_type: TaskType,
    recommended_duration_minutes: int,
    title: Optional[str] = None,
    description: Optional[str] = None,
    estimated_duration_minutes: Optional[int] = None,
    is_estimated: bool = False,
    # Video fields
    course_id: Optional[uuid.UUID] = None,
    course_chapter_id: Optional[uuid.UUID] = None,
    video_start_num: Optional[int] = None,
    video_end_num: Optional[int] = None,
    video_count: Optional[int] = None,
    # Test fields
    book_id: Optional[uuid.UUID] = None,
    book_chapter_id: Optional[uuid.UUID] = None,
    test_start_num: Optional[int] = None,
    test_end_num: Optional[int] = None,
    tutor_id: Optional[uuid.UUID] = None,
) -> PlanAssignment:
    if not _lock_study_plan_row(db, plan_id, share=True):
        raise PlanNotFoundError(f"Plan with id {plan_id} not found.")
    plan = get_study_plan(db, plan_id, tutor_id=tutor_id, populate_existing=True)
    if not plan:
        raise PlanNotFoundError(f"Plan with id {plan_id} not found.")

    if plan.status == PlanStatus.ARCHIVED:
        raise PlanValidationError("Cannot add assignments to an archived study plan.")

    if scheduled_date < plan.start_date or scheduled_date > plan.end_date:
        raise PlanValidationError(
            f"Scheduled date {scheduled_date.isoformat()} falls outside the plan date range "
            f"({plan.start_date.isoformat()} to {plan.end_date.isoformat()})."
        )

    if recommended_duration_minutes < 0:
        raise PlanValidationError("Recommended duration cannot be negative.")

    subject = db.query(Subject).filter(Subject.id == subject_id).first()
    if not subject:
        raise PlanValidationError(f"Subject with id {subject_id} not found.")

    student = plan.student
    if student:
        effective_subjects = get_student_effective_subjects(student)
        if effective_subjects and subject_id not in {s.id for s in effective_subjects}:
            raise PlanValidationError(f"Subject '{subject.name}' is not assigned to student '{student.full_name}'.")

    course_snapshot = None
    course_chapter_snapshot = None
    book_snapshot = None
    book_chapter_snapshot = None
    final_title = (title or "").strip()

    if task_type == TaskType.VIDEO:
        if not course_id or not course_chapter_id:
            raise PlanValidationError("Course and chapter are required for video assignments.")
        course = db.query(Course).filter(Course.id == course_id).first()
        chapter = db.query(CourseChapter).filter(CourseChapter.id == course_chapter_id).first()
        if not course or not chapter:
            raise PlanValidationError("Selected course or chapter not found.")
        if chapter.course_id != course.id:
            raise PlanValidationError("Selected chapter does not belong to the chosen course.")

        if course.subject_id != subject_id:
            raise PlanValidationError(f"Course '{course.name}' does not belong to subject '{subject.name}'.")

        if student and student.grade:
            if normalize_grade(course.grade) != normalize_grade(student.grade):
                raise PlanValidationError(f"Course '{course.name}' (Grade {course.grade}) does not match student's grade ({student.grade}).")

        course_snapshot = f"{course.teacher_name} - {course.name}"
        course_chapter_snapshot = chapter.name

        calc_count = video_count
        if video_start_num is not None or video_end_num is not None:
            if video_start_num is None or video_end_num is None:
                raise PlanValidationError("Both starting and ending video numbers are required when specifying a range.")
            if video_start_num < 1 or video_end_num < video_start_num:
                raise PlanValidationError("Invalid video number range.")
            if video_end_num > chapter.video_count:
                raise PlanValidationError(
                    f"Ending video number ({video_end_num}) exceeds available videos ({chapter.video_count}) in chapter '{chapter.name}'."
                )
            calc_count = video_end_num - video_start_num + 1

        if not calc_count or calc_count <= 0:
            calc_count = 1

        video_count = calc_count
        if not final_title:
            range_info = f"Videos {video_start_num}-{video_end_num}" if video_start_num and video_end_num else f"{video_count} video(s)"
            final_title = f"{course.teacher_name}: {chapter.name} ({range_info})"

    elif task_type == TaskType.TEST:
        if not book_id or not book_chapter_id:
            raise PlanValidationError("Book and chapter are required for test assignments.")
        book = db.query(Book).filter(Book.id == book_id).first()
        bchapter = db.query(BookChapter).filter(BookChapter.id == book_chapter_id).first()
        if not book or not bchapter:
            raise PlanValidationError("Selected book or chapter not found.")
        if bchapter.book_id != book.id:
            raise PlanValidationError("Selected chapter does not belong to the chosen book.")

        if book.subject_id != subject_id:
            raise PlanValidationError(f"Book '{book.title}' does not belong to subject '{subject.name}'.")

        if student and student.grade:
            if normalize_grade(book.grade) != normalize_grade(student.grade):
                raise PlanValidationError(f"Book '{book.title}' (Grade {book.grade}) does not match student's grade ({student.grade}).")

        if test_start_num is None or test_end_num is None:
            raise PlanValidationError("Starting and ending test numbers are required.")
        if test_start_num < 1 or test_end_num < test_start_num:
            raise PlanValidationError("Starting test number must be >= 1 and <= ending test number.")
        if test_end_num > bchapter.test_count:
            raise PlanValidationError(
                f"Ending test number ({test_end_num}) exceeds available tests ({bchapter.test_count}) in chapter '{bchapter.title}'."
            )

        test_count = test_end_num - test_start_num + 1
        book_snapshot = book.title
        book_chapter_snapshot = bchapter.title
        if not final_title:
            final_title = f"{book.title}: {bchapter.title} (Tests {test_start_num}-{test_end_num})"

    elif task_type == TaskType.CUSTOM:
        if not final_title:
            raise PlanValidationError("Title is required for custom assignments.")
        is_estimated = False
        estimated_duration_minutes = None

    # Determine display order for this day and subject
    max_order = (
        db.query(func.coalesce(func.max(PlanAssignment.display_order), 0))
        .filter(
            PlanAssignment.study_plan_id == plan_id,
            PlanAssignment.scheduled_date == scheduled_date,
            PlanAssignment.subject_id == subject_id,
        )
        .scalar()
    )

    assignment = PlanAssignment(
        study_plan_id=plan_id,
        student_id=plan.student_id,
        subject_id=subject_id,
        task_type=task_type,
        scheduled_date=scheduled_date,
        display_order=max_order + 1,
        title=final_title,
        description=description.strip() if description else None,
        recommended_duration_minutes=recommended_duration_minutes,
        estimated_duration_minutes=estimated_duration_minutes,
        is_estimated=is_estimated,
        course_id=course_id,
        course_chapter_id=course_chapter_id,
        video_start_num=video_start_num,
        video_end_num=video_end_num,
        video_count=video_count,
        course_name_snapshot=course_snapshot,
        course_chapter_name_snapshot=course_chapter_snapshot,
        book_id=book_id,
        book_chapter_id=book_chapter_id,
        test_start_num=test_start_num,
        test_end_num=test_end_num,
        test_count=test_count if task_type == TaskType.TEST else None,
        book_title_snapshot=book_snapshot,
        book_chapter_title_snapshot=book_chapter_snapshot,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return assignment


def get_assignment(
    db: Session,
    assignment_id: uuid.UUID,
    tutor_id: Optional[uuid.UUID] = None,
    student_id: Optional[uuid.UUID] = None,
) -> Optional[PlanAssignment]:
    query = db.query(PlanAssignment).filter(PlanAssignment.id == assignment_id)
    if tutor_id is not None:
        query = query.join(StudyPlan, PlanAssignment.study_plan_id == StudyPlan.id).filter(StudyPlan.tutor_id == tutor_id)
    if student_id is not None:
        query = query.filter(PlanAssignment.student_id == student_id)
    return query.first()


def update_assignment(
    db: Session,
    assignment_id: uuid.UUID,
    title: Optional[str] = None,
    description: Optional[str] = None,
    recommended_duration_minutes: Optional[int] = None,
    scheduled_date: Optional[date] = None,
    subject_id: Optional[uuid.UUID] = None,
    display_order: Optional[int] = None,
    tutor_id: Optional[uuid.UUID] = None,
) -> PlanAssignment:
    assignment = _lock_assignment_with_plan(db, assignment_id, share_plan=True)
    if not assignment or (tutor_id is not None and (not assignment.study_plan or assignment.study_plan.tutor_id != tutor_id)):
        raise AssignmentNotFoundError(f"Assignment with id {assignment_id} not found.")

    if assignment.study_plan and assignment.study_plan.status == PlanStatus.ARCHIVED:
        raise PlanValidationError("Cannot modify assignments in an archived study plan.")

    if assignment.is_completed:
        if (scheduled_date is not None and scheduled_date != assignment.scheduled_date) or (
            subject_id is not None and subject_id != assignment.subject_id
        ):
            raise PlanValidationError(
                "Cannot move or change the subject of a completed assignment. Reset its completion status first."
            )

    if title is not None:
        clean_title = title.strip()
        if not clean_title:
            raise PlanValidationError("Assignment title cannot be empty.")
        assignment.title = clean_title

    if description is not None:
        assignment.description = description.strip() if description else None

    if recommended_duration_minutes is not None:
        if recommended_duration_minutes < 0:
            raise PlanValidationError("Recommended duration cannot be negative.")
        assignment.recommended_duration_minutes = recommended_duration_minutes

    if scheduled_date is not None:
        plan = assignment.study_plan
        if scheduled_date < plan.start_date or scheduled_date > plan.end_date:
            raise PlanValidationError("Scheduled date must fall within the plan date range.")
        assignment.scheduled_date = scheduled_date

    if subject_id is not None:
        sub = db.query(Subject).filter(Subject.id == subject_id).first()
        if not sub:
            raise PlanValidationError(f"Subject with id {subject_id} not found.")
        student = assignment.study_plan.student if assignment.study_plan else None
        if student:
            effective_subjects = get_student_effective_subjects(student)
            if effective_subjects and subject_id not in {s.id for s in effective_subjects}:
                raise PlanValidationError(f"Subject '{sub.name}' is not assigned to student '{student.full_name}'.")
        assignment.subject_id = subject_id

    if display_order is not None:
        assignment.display_order = display_order

    db.commit()
    db.refresh(assignment)
    return assignment


def delete_assignment(db: Session, assignment_id: uuid.UUID, tutor_id: Optional[uuid.UUID] = None) -> None:
    assignment = _lock_assignment_with_plan(db, assignment_id, share_plan=True)
    if not assignment or (tutor_id is not None and (not assignment.study_plan or assignment.study_plan.tutor_id != tutor_id)):
        raise AssignmentNotFoundError(f"Assignment with id {assignment_id} not found.")
    if assignment.study_plan and assignment.study_plan.status == PlanStatus.ARCHIVED:
        raise PlanValidationError("Cannot delete assignments from an archived study plan.")
    if assignment.is_completed:
        raise PlanValidationError("Cannot delete a completed assignment. Reset its completion status first.")
    has_audit_history = (
        db.query(CompletionAuditLog.id)
        .filter(CompletionAuditLog.assignment_id == assignment.id)
        .first()
    )
    if has_audit_history:
        raise PlanValidationError("Cannot delete an assignment with existing completion audit history.")
    db.delete(assignment)
    db.commit()


def reorder_assignment(
    db: Session,
    assignment_id: uuid.UUID,
    direction: str,  # 'up' or 'down'
    tutor_id: Optional[uuid.UUID] = None,
) -> PlanAssignment:
    """Move assignment up or down within its cell (same scheduled_date and subject_id)."""
    assignment = _lock_assignment_with_plan(db, assignment_id, share_plan=True)
    if not assignment or (tutor_id is not None and (not assignment.study_plan or assignment.study_plan.tutor_id != tutor_id)):
        raise AssignmentNotFoundError(f"Assignment with id {assignment_id} not found.")
    if assignment.study_plan and assignment.study_plan.status == PlanStatus.ARCHIVED:
        raise PlanValidationError("Cannot reorder assignments in an archived study plan.")

    cell_assignments = (
        db.query(PlanAssignment)
        .filter(
            PlanAssignment.study_plan_id == assignment.study_plan_id,
            PlanAssignment.scheduled_date == assignment.scheduled_date,
            PlanAssignment.subject_id == assignment.subject_id,
        )
        .order_by(PlanAssignment.display_order, PlanAssignment.created_at)
        .all()
    )

    idx = next((i for i, a in enumerate(cell_assignments) if a.id == assignment_id), None)
    if idx is None:
        return assignment

    if direction == "up" and idx > 0:
        other = cell_assignments[idx - 1]
        assignment.display_order, other.display_order = other.display_order, assignment.display_order
        db.commit()
        db.refresh(assignment)
    elif direction == "down" and idx < len(cell_assignments) - 1:
        other = cell_assignments[idx + 1]
        assignment.display_order, other.display_order = other.display_order, assignment.display_order
        db.commit()
        db.refresh(assignment)

    return assignment


def complete_assignment(
    db: Session,
    assignment_id: uuid.UUID,
    student_id: uuid.UUID,
    actual_duration_minutes: Optional[int] = None,
    performed_by_id: Optional[uuid.UUID] = None,
) -> PlanAssignment:
    """Mark an assignment completed with fresh server timestamp and audit record."""
    assignment = _lock_assignment_with_plan(db, assignment_id, share_plan=True)
    if not assignment:
        raise AssignmentNotFoundError(f"Assignment with id {assignment_id} not found.")

    if assignment.student_id != student_id:
        raise PlanValidationError("Unauthorized: assignment does not belong to this student.")

    if assignment.study_plan and assignment.study_plan.status == PlanStatus.ARCHIVED:
        raise PlanValidationError("Cannot complete assignments in an archived plan.")

    if actual_duration_minutes is not None and actual_duration_minutes <= 0:
        raise PlanValidationError("Actual duration must be a positive number of minutes.")

    # Idempotent completion: if already completed, preserve original completed_at, duration, and audit history
    if assignment.is_completed:
        return assignment

    if actual_duration_minutes is not None:
        final_actual = actual_duration_minutes
    else:
        final_actual = assignment.recommended_duration_minutes if assignment.recommended_duration_minutes > 0 else 30

    assignment.is_completed = True
    assignment.completed_at = now_utc()
    assignment.actual_duration_minutes = final_actual

    audit = CompletionAuditLog(
        assignment_id=assignment.id,
        student_id=student_id,
        performed_by_id=performed_by_id or student_id,
        action=CompletionAuditAction.COMPLETED,
        recorded_completed_at=assignment.completed_at,
        actual_duration_minutes=final_actual,
    )
    db.add(audit)
    db.commit()
    db.refresh(assignment)
    return assignment


def undo_assignment_completion(
    db: Session,
    assignment_id: uuid.UUID,
    student_id: uuid.UUID,
) -> PlanAssignment:
    """Return a completed assignment to pending state and log audit entry."""
    assignment = _lock_assignment_with_plan(db, assignment_id, share_plan=True)
    if not assignment:
        raise AssignmentNotFoundError(f"Assignment with id {assignment_id} not found.")

    if assignment.student_id != student_id:
        raise PlanValidationError("Unauthorized: assignment does not belong to this student.")

    if assignment.study_plan and assignment.study_plan.status == PlanStatus.ARCHIVED:
        raise PlanValidationError("Cannot undo assignments in an archived plan.")

    if not assignment.is_completed:
        raise PlanValidationError("Assignment is not marked as completed.")

    prev_completed_at = assignment.completed_at
    prev_actual = assignment.actual_duration_minutes

    assignment.is_completed = False
    assignment.completed_at = None
    assignment.actual_duration_minutes = None

    audit = CompletionAuditLog(
        assignment_id=assignment.id,
        student_id=student_id,
        performed_by_id=student_id,
        action=CompletionAuditAction.STUDENT_UNDO,
        recorded_completed_at=prev_completed_at,
        actual_duration_minutes=prev_actual,
        note="Completion undone by student",
    )
    db.add(audit)
    db.commit()
    db.refresh(assignment)
    return assignment


def reset_assignment_completion(
    db: Session,
    assignment_id: uuid.UUID,
    tutor_id: uuid.UUID,
    note: Optional[str] = None,
) -> PlanAssignment:
    """Tutor-only: reset an accidentally completed assignment while preserving audit history."""
    assignment = _lock_assignment_with_plan(db, assignment_id, share_plan=True)
    if not assignment or (not assignment.study_plan or assignment.study_plan.tutor_id != tutor_id):
        raise AssignmentNotFoundError(f"Assignment with id {assignment_id} not found.")
    if assignment.study_plan.status == PlanStatus.ARCHIVED:
        raise PlanValidationError("Cannot reset assignment completion in an archived study plan.")
    if not assignment.is_completed:
        raise PlanValidationError("Assignment is not marked as completed.")

    prev_completed_at = assignment.completed_at
    prev_actual = assignment.actual_duration_minutes
    assignment.is_completed = False
    assignment.completed_at = None
    assignment.actual_duration_minutes = None

    audit = CompletionAuditLog(
        assignment_id=assignment.id,
        student_id=assignment.student_id,
        performed_by_id=tutor_id,
        action=CompletionAuditAction.RESET,
        recorded_completed_at=prev_completed_at,
        actual_duration_minutes=prev_actual,
        note=note or "Reset by tutor",
    )
    db.add(audit)
    db.commit()
    db.refresh(assignment)
    return assignment


def get_assignment_audit_logs(
    db: Session,
    assignment_id: uuid.UUID,
    tutor_id: Optional[uuid.UUID] = None,
) -> List[CompletionAuditLog]:
    """Retrieve audit logs for an assignment, newest first."""
    query = (
        db.query(CompletionAuditLog)
        .join(PlanAssignment, CompletionAuditLog.assignment_id == PlanAssignment.id)
        .join(StudyPlan, PlanAssignment.study_plan_id == StudyPlan.id)
        .filter(CompletionAuditLog.assignment_id == assignment_id)
    )
    if tutor_id is not None:
        query = query.filter(StudyPlan.tutor_id == tutor_id)
    return query.order_by(desc(CompletionAuditLog.created_at)).all()


def get_student_completion_history(
    db: Session,
    student_id: uuid.UUID,
    limit: Optional[int] = None,
    tutor_id: Optional[uuid.UUID] = None,
) -> List[PlanAssignment]:
    """Retrieve chronologically completed assignments for a student."""
    query = (
        db.query(PlanAssignment)
        .filter(
            PlanAssignment.student_id == student_id,
            PlanAssignment.is_completed.is_(True),
        )
    )
    if tutor_id is not None:
        query = query.join(StudyPlan, PlanAssignment.study_plan_id == StudyPlan.id).filter(
            StudyPlan.tutor_id == tutor_id
        )
    query = query.order_by(desc(PlanAssignment.completed_at))
    if limit:
        query = query.limit(limit)
    return query.all()


def get_student_dashboard_data(db: Session, student: User) -> dict:
    active_plan = get_active_student_plan(db, student.id)
    if not active_plan:
        return {"has_plan": False}

    from app.services.academic_service import get_student_effective_subjects
    effective_subjects = get_student_effective_subjects(student)
    assignments = active_plan.assignments
    today = today_local(getattr(student, "timezone", None))

    today_tasks = [a for a in assignments if a.scheduled_date == today]
    today_tasks_by_subject: Dict[uuid.UUID, List[PlanAssignment]] = {}
    today_completed = 0
    today_total_minutes = 0

    for t in today_tasks:
        today_tasks_by_subject.setdefault(t.subject_id, []).append(t)
        if t.is_completed:
            today_completed += 1
        today_total_minutes += t.recommended_duration_minutes or 0

    today_remaining = len(today_tasks) - today_completed
    total_tasks = len(assignments)
    completed_tasks = sum(1 for a in assignments if a.is_completed)
    remaining_tasks = total_tasks - completed_tasks
    completion_percentage = round((completed_tasks / total_tasks) * 100) if total_tasks > 0 else 0

    days = [active_plan.start_date + timedelta(days=i) for i in range(14)]
    upcoming_days = []
    for d in days:
        if d > today:
            d_tasks = [a for a in assignments if a.scheduled_date == d]
            d_mins = sum(a.recommended_duration_minutes or 0 for a in d_tasks)
            upcoming_days.append({
                "date": d,
                "weekday": d.strftime("%A"),
                "total_tasks": len(d_tasks),
                "total_minutes": d_mins,
                "formatted_duration": format_duration_minutes(d_mins),
                "completed_tasks": sum(1 for a in d_tasks if a.is_completed),
            })

    return {
        "has_plan": True,
        "plan": active_plan,
        "today": today,
        "today_weekday": today.strftime("%A"),
        "today_tasks": today_tasks,
        "today_tasks_by_subject": today_tasks_by_subject,
        "today_total_minutes": today_total_minutes,
        "today_total_formatted": format_duration_minutes(today_total_minutes),
        "today_completed_count": today_completed,
        "today_remaining_count": today_remaining,
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "remaining_tasks": remaining_tasks,
        "completion_percentage": completion_percentage,
        "upcoming_days": upcoming_days,
        "effective_subjects": effective_subjects,
    }


def get_student_monitoring_data(db: Session, student_id: uuid.UUID, tutor_id: Optional[uuid.UUID] = None) -> dict:
    student = db.query(User).filter(User.id == student_id).first()
    if not student:
        raise ValueError(f"Student {student_id} not found.")

    from app.services.academic_service import get_student_effective_subjects
    effective_subjects = get_student_effective_subjects(student)
    active_plan = get_active_student_plan(db, student_id, tutor_id=tutor_id)
    today = today_local(getattr(student, "timezone", None))

    active_plan_data = None
    if active_plan:
        assignments = active_plan.assignments
        total_tasks = len(assignments)
        completed_tasks = sum(1 for a in assignments if a.is_completed)
        pending_tasks = total_tasks - completed_tasks
        pct = round((completed_tasks / total_tasks) * 100) if total_tasks > 0 else 0

        subject_breakdown = []
        for sub in effective_subjects:
            sub_tasks = [a for a in assignments if a.subject_id == sub.id]
            sub_total = len(sub_tasks)
            sub_comp = sum(1 for a in sub_tasks if a.is_completed)
            sub_pct = round((sub_comp / sub_total) * 100) if sub_total > 0 else 0
            sub_mins = sum(a.recommended_duration_minutes or 0 for a in sub_tasks)
            subject_breakdown.append({
                "subject": sub,
                "total_tasks": sub_total,
                "completed_tasks": sub_comp,
                "completion_percentage": sub_pct,
                "total_minutes": sub_mins,
                "formatted_duration": format_duration_minutes(sub_mins),
            })

        days = [active_plan.start_date + timedelta(days=i) for i in range(14)]
        daily_progress = []
        expected_so_far = 0
        completed_so_far = 0
        for i, d in enumerate(days, 1):
            d_tasks = [a for a in assignments if a.scheduled_date == d]
            d_total = len(d_tasks)
            d_comp = sum(1 for a in d_tasks if a.is_completed)
            d_mins = sum(a.recommended_duration_minutes or 0 for a in d_tasks)
            if d <= today:
                expected_so_far += d_total
                completed_so_far += d_comp
            daily_progress.append({
                "date": d,
                "day_num": i,
                "weekday": d.strftime("%a"),
                "total_tasks": d_total,
                "completed_tasks": d_comp,
                "total_minutes": d_mins,
                "is_past": d < today,
                "is_today": d == today,
                "is_future": d > today,
            })

        behind_count = max(0, expected_so_far - completed_so_far)
        is_behind = behind_count > 0 and active_plan.start_date <= today

        active_plan_data = {
            "plan": active_plan,
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "pending_tasks": pending_tasks,
            "completion_percentage": pct,
            "subject_breakdown": subject_breakdown,
            "daily_progress": daily_progress,
            "is_behind": is_behind,
            "behind_count": behind_count,
            "expected_so_far": expected_so_far,
            "completed_so_far": completed_so_far,
        }

    recent_completed = get_student_completion_history(db, student_id, limit=10, tutor_id=tutor_id)
    all_plans = list_student_plans(db, student_id, tutor_id=tutor_id)
    archived_plans = [p for p in all_plans if p.status == PlanStatus.ARCHIVED or (active_plan and p.id != active_plan.id)]

    return {
        "student": student,
        "effective_subjects": effective_subjects,
        "active_plan_data": active_plan_data,
        "recent_completed": recent_completed,
        "archived_plans": archived_plans,
    }


