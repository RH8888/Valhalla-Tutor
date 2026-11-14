import uuid
from datetime import date, timedelta
import pytest
from sqlalchemy.orm import Session

from app.models.book import Book, BookChapter
from app.models.course import Course, CourseChapter
from app.models.plan import PlanAssignment, PlanStatus, StudyPlan, TaskType
from app.models.subject import Subject
from app.models.user import User, UserRole
from app.services.plan_service import (
    calculate_plan_totals,
    complete_assignment,
    create_assignment,
    create_study_plan,
    estimate_test_duration,
    estimate_video_duration,
    format_duration_minutes,
    get_active_student_plan,
    publish_study_plan,
    PlanValidationError,
)


def test_format_duration_minutes():
    assert format_duration_minutes(0) == "0 minutes"
    assert format_duration_minutes(45) == "45 minutes"
    assert format_duration_minutes(60) == "1 hour"
    assert format_duration_minutes(120) == "2 hours"
    assert format_duration_minutes(210) == "3 hours 30 minutes"
    assert format_duration_minutes(75) == "1 hour 15 minutes"


def test_create_and_publish_study_plan(db_session: Session, tutor_user: User):
    student = User(
        username="student_test_1",
        full_name="Student Test One",
        hashed_password="pw",
        role=UserRole.STUDENT,
    )
    db_session.add(student)
    db_session.commit()

    start = date(2026, 11, 15)
    plan = create_study_plan(db_session, student_id=student.id, tutor_id=tutor_user.id, start_date=start)

    assert plan.status == PlanStatus.DRAFT
    assert plan.start_date == start
    assert plan.end_date == start + timedelta(days=13)
    assert (plan.end_date - plan.start_date).days == 13

    # Publish plan
    published = publish_study_plan(db_session, plan.id)
    assert published.status == PlanStatus.PUBLISHED
    assert get_active_student_plan(db_session, student.id).id == plan.id

    # Create a 2nd plan and publish it -> 1st plan should become ARCHIVED
    plan2 = create_study_plan(db_session, student_id=student.id, tutor_id=tutor_user.id, start_date=start + timedelta(days=14))
    publish_study_plan(db_session, plan2.id)

    db_session.refresh(plan)
    assert plan.status == PlanStatus.ARCHIVED
    assert plan2.status == PlanStatus.PUBLISHED
    assert get_active_student_plan(db_session, student.id).id == plan2.id


def test_task_creation_and_validation(db_session: Session, tutor_user: User):
    student = User(
        username="student_test_2",
        full_name="Student Test Two",
        hashed_password="pw",
        role=UserRole.STUDENT,
    )
    subject = Subject(name="Mathematics")
    db_session.add_all([student, subject])
    db_session.commit()

    book = Book(subject_id=subject.id, title="Calculus 1", grade="12")
    course = Course(subject_id=subject.id, teacher_name="Dr. Smith", name="Calculus Videos", grade="12")
    db_session.add_all([book, course])
    db_session.commit()

    bchapter = BookChapter(book_id=book.id, title="Derivatives", test_count=40, display_order=1)
    cchapter = CourseChapter(course_id=course.id, name="Limits & Continuity", video_count=10, display_order=1)
    db_session.add_all([bchapter, cchapter])
    db_session.commit()

    start = date(2026, 11, 15)
    plan = create_study_plan(db_session, student_id=student.id, tutor_id=tutor_user.id, start_date=start)

    # 1. Custom task
    custom_task = create_assignment(
        db_session,
        plan_id=plan.id,
        scheduled_date=start,
        subject_id=subject.id,
        task_type=TaskType.CUSTOM,
        recommended_duration_minutes=45,
        title="Review chapter formulas",
    )
    assert custom_task.task_type == TaskType.CUSTOM
    assert custom_task.recommended_duration_minutes == 45
    assert custom_task.is_estimated is False

    # 2. Test task with valid range
    test_task = create_assignment(
        db_session,
        plan_id=plan.id,
        scheduled_date=start + timedelta(days=1),
        subject_id=subject.id,
        task_type=TaskType.TEST,
        recommended_duration_minutes=90,
        book_id=book.id,
        book_chapter_id=bchapter.id,
        test_start_num=1,
        test_end_num=20,
    )
    assert test_task.test_count == 20
    assert test_task.book_title_snapshot == "Calculus 1"
    assert test_task.book_chapter_title_snapshot == "Derivatives"

    # Test range exceeding chapter test count should fail
    with pytest.raises(PlanValidationError) as exc:
        create_assignment(
            db_session,
            plan_id=plan.id,
            scheduled_date=start + timedelta(days=2),
            subject_id=subject.id,
            task_type=TaskType.TEST,
            recommended_duration_minutes=60,
            book_id=book.id,
            book_chapter_id=bchapter.id,
            test_start_num=1,
            test_end_num=45,  # Exceeds 40
        )
    assert "exceeds available tests" in str(exc.value)

    # 3. Video task
    video_task = create_assignment(
        db_session,
        plan_id=plan.id,
        scheduled_date=start + timedelta(days=2),
        subject_id=subject.id,
        task_type=TaskType.VIDEO,
        recommended_duration_minutes=60,
        course_id=course.id,
        course_chapter_id=cchapter.id,
        video_start_num=1,
        video_end_num=3,
    )
    assert video_task.video_count == 3
    assert "Dr. Smith" in video_task.course_name_snapshot

    # Scheduled date outside plan date range should fail
    with pytest.raises(PlanValidationError):
        create_assignment(
            db_session,
            plan_id=plan.id,
            scheduled_date=start + timedelta(days=15),
            subject_id=subject.id,
            task_type=TaskType.CUSTOM,
            recommended_duration_minutes=30,
            title="Out of range",
        )

    # 4. Student completion
    completed = complete_assignment(db_session, custom_task.id, student.id)
    assert completed.is_completed is True
    assert completed.completed_at is not None


def test_historical_duration_estimates(db_session: Session, tutor_user: User):
    student = User(
        username="student_test_3",
        full_name="Student Test Three",
        hashed_password="pw",
        role=UserRole.STUDENT,
    )
    subject = Subject(name="Physics")
    db_session.add_all([student, subject])
    db_session.commit()

    book = Book(subject_id=subject.id, title="Physics Book A", grade="12")
    course = Course(subject_id=subject.id, teacher_name="Prof. Newton", name="Physics Course A", grade="12")
    db_session.add_all([book, course])
    db_session.commit()

    bchapter = BookChapter(book_id=book.id, title="Mechanics", test_count=100, display_order=1)
    cchapter = CourseChapter(course_id=course.id, name="Kinematics", video_count=20, display_order=1)
    db_session.add_all([bchapter, cchapter])
    db_session.commit()

    # When no historical data exists:
    est_no_history = estimate_test_duration(db_session, student.id, book.id, test_count=50)
    assert est_no_history.is_historical is False
    assert est_no_history.suggested_duration_minutes is None

    # Create previous plan with completed assignments
    # Spec example 1: 75 tests completed with recorded duration of 3 hours (180 mins) -> 2.4 min/test
    # Then for 50 tests -> 120 mins!
    start1 = date(2026, 10, 1)
    past_plan = create_study_plan(db_session, student_id=student.id, tutor_id=tutor_user.id, start_date=start1)

    past_test = create_assignment(
        db_session,
        plan_id=past_plan.id,
        scheduled_date=start1,
        subject_id=subject.id,
        task_type=TaskType.TEST,
        recommended_duration_minutes=180,
        book_id=book.id,
        book_chapter_id=bchapter.id,
        test_start_num=1,
        test_end_num=75,
    )
    complete_assignment(db_session, past_test.id, student.id)

    # Spec example 2: 12 videos completed with duration of 4 hours (240 mins) -> 20 min/video
    # Then for 6 videos -> 120 mins!
    past_video = create_assignment(
        db_session,
        plan_id=past_plan.id,
        scheduled_date=start1 + timedelta(days=1),
        subject_id=subject.id,
        task_type=TaskType.VIDEO,
        recommended_duration_minutes=240,
        course_id=course.id,
        course_chapter_id=cchapter.id,
        video_start_num=1,
        video_end_num=12,
    )
    complete_assignment(db_session, past_video.id, student.id)

    # Test calculation
    est_test = estimate_test_duration(db_session, student.id, book.id, test_count=50)
    assert est_test.is_historical is True
    assert est_test.average_unit_minutes == 2.4
    assert est_test.suggested_duration_minutes == 120
    assert "2.4 min/test" in est_test.basis_text

    # Video calculation
    est_video = estimate_video_duration(db_session, student.id, course.id, video_count=6)
    assert est_video.is_historical is True
    assert est_video.average_unit_minutes == 20.0
    assert est_video.suggested_duration_minutes == 120
    assert "20.0 min/video" in est_video.basis_text

    # Check that another book gets no history
    book_b = Book(subject_id=subject.id, title="Physics Book B", grade="12")
    db_session.add(book_b)
    db_session.commit()
    est_diff_book = estimate_test_duration(db_session, student.id, book_b.id, test_count=50)
    assert est_diff_book.is_historical is False
    assert est_diff_book.suggested_duration_minutes is None


def test_calculate_plan_totals(db_session: Session, tutor_user: User):
    student = User(username="st_totals", full_name="Student Totals", hashed_password="pw", role=UserRole.STUDENT)
    sub1 = Subject(name="Math")
    sub2 = Subject(name="Chem")
    db_session.add_all([student, sub1, sub2])
    db_session.commit()

    start = date(2026, 11, 15)
    plan = create_study_plan(db_session, student.id, tutor_user.id, start)
    days = [start + timedelta(days=i) for i in range(14)]

    # Add 45 mins Math on day 1
    a1 = create_assignment(db_session, plan.id, start, sub1.id, TaskType.CUSTOM, 45, title="Math T1")
    # Add 60 mins Chem on day 1
    a2 = create_assignment(db_session, plan.id, start, sub2.id, TaskType.CUSTOM, 60, title="Chem T1")
    # Add 90 mins Math on day 2
    a3 = create_assignment(db_session, plan.id, start + timedelta(days=1), sub1.id, TaskType.CUSTOM, 90, title="Math T2")

    daily, subject, total = calculate_plan_totals([a1, a2, a3], days, [sub1, sub2])
    assert daily[start] == 105
    assert daily[start + timedelta(days=1)] == 90
    assert daily[start + timedelta(days=2)] == 0
    assert subject[sub1.id] == 135
    assert subject[sub2.id] == 60
    assert total == 195


def test_historical_rolling_average_last_3_plans(db_session: Session, tutor_user: User):
    student = User(username="st_roll", full_name="Student Rolling", hashed_password="pw", role=UserRole.STUDENT)
    subject = Subject(name="Biology")
    db_session.add_all([student, subject])
    db_session.commit()

    book = Book(subject_id=subject.id, title="Bio Book", grade="11")
    db_session.add(book)
    db_session.commit()

    bchapter = BookChapter(book_id=book.id, title="Cells", test_count=200, display_order=1)
    db_session.add(bchapter)
    db_session.commit()

    # Plan 1 (oldest): 10 tests, 100 minutes (10 min/test) -> should be excluded by rolling 3!
    p1 = create_study_plan(db_session, student.id, tutor_user.id, date(2026, 7, 1))
    a1 = create_assignment(db_session, p1.id, date(2026, 7, 1), subject.id, TaskType.TEST, 100, book_id=book.id, book_chapter_id=bchapter.id, test_start_num=1, test_end_num=10)
    complete_assignment(db_session, a1.id, student.id)

    # Plan 2: 10 tests, 20 minutes (2 min/test)
    p2 = create_study_plan(db_session, student.id, tutor_user.id, date(2026, 8, 1))
    a2 = create_assignment(db_session, p2.id, date(2026, 8, 1), subject.id, TaskType.TEST, 20, book_id=book.id, book_chapter_id=bchapter.id, test_start_num=11, test_end_num=20)
    complete_assignment(db_session, a2.id, student.id)

    # Plan 3: 10 tests, 20 minutes (2 min/test)
    p3 = create_study_plan(db_session, student.id, tutor_user.id, date(2026, 9, 1))
    a3 = create_assignment(db_session, p3.id, date(2026, 9, 1), subject.id, TaskType.TEST, 20, book_id=book.id, book_chapter_id=bchapter.id, test_start_num=21, test_end_num=30)
    complete_assignment(db_session, a3.id, student.id)

    # Plan 4 (newest): 10 tests, 20 minutes (2 min/test)
    p4 = create_study_plan(db_session, student.id, tutor_user.id, date(2026, 10, 1))
    a4 = create_assignment(db_session, p4.id, date(2026, 10, 1), subject.id, TaskType.TEST, 20, book_id=book.id, book_chapter_id=bchapter.id, test_start_num=31, test_end_num=40)
    complete_assignment(db_session, a4.id, student.id)

    # Estimate for 15 tests: If last 3 plans are used (P2, P3, P4):
    # Total tests = 30, Total mins = 60 -> 2.0 min/test -> 15 tests * 2.0 = 30 mins.
    # (If P1 was included, total tests = 40, mins = 160 -> 4.0 min/test -> 60 mins).
    est = estimate_test_duration(db_session, student.id, book.id, test_count=15)
    assert est.is_historical is True
    assert est.average_unit_minutes == 2.0
    assert est.suggested_duration_minutes == 30
    assert est.plans_count == 3


def test_video_historical_rolling_average_last_3_plans(db_session: Session, tutor_user: User):
    student = User(username="st_video_roll", full_name="Student Video Rolling", hashed_password="pw", role=UserRole.STUDENT)
    subject = Subject(name="Physics")
    db_session.add_all([student, subject])
    db_session.commit()

    course = Course(subject_id=subject.id, teacher_name="Prof. Bohr", name="Quantum Physics", grade="12")
    db_session.add(course)
    db_session.commit()

    cchapter = CourseChapter(course_id=course.id, name="Wave Mechanics", video_count=50, display_order=1)
    db_session.add(cchapter)
    db_session.commit()

    # Plan 1 (oldest): 2 videos, 100 minutes (50 min/vid) -> excluded by rolling 3
    p1 = create_study_plan(db_session, student.id, tutor_user.id, date(2026, 7, 1))
    a1 = create_assignment(db_session, p1.id, date(2026, 7, 1), subject.id, TaskType.VIDEO, 100, course_id=course.id, course_chapter_id=cchapter.id, video_start_num=1, video_end_num=2)
    complete_assignment(db_session, a1.id, student.id)

    # Plan 2: 2 videos, 20 minutes (10 min/vid)
    p2 = create_study_plan(db_session, student.id, tutor_user.id, date(2026, 8, 1))
    a2 = create_assignment(db_session, p2.id, date(2026, 8, 1), subject.id, TaskType.VIDEO, 20, course_id=course.id, course_chapter_id=cchapter.id, video_start_num=3, video_end_num=4)
    complete_assignment(db_session, a2.id, student.id)

    # Plan 3: 2 videos, 20 minutes (10 min/vid)
    p3 = create_study_plan(db_session, student.id, tutor_user.id, date(2026, 9, 1))
    a3 = create_assignment(db_session, p3.id, date(2026, 9, 1), subject.id, TaskType.VIDEO, 20, course_id=course.id, course_chapter_id=cchapter.id, video_start_num=5, video_end_num=6)
    complete_assignment(db_session, a3.id, student.id)

    # Plan 4 (newest): 2 videos, 20 minutes (10 min/vid)
    p4 = create_study_plan(db_session, student.id, tutor_user.id, date(2026, 10, 1))
    a4 = create_assignment(db_session, p4.id, date(2026, 10, 1), subject.id, TaskType.VIDEO, 20, course_id=course.id, course_chapter_id=cchapter.id, video_start_num=7, video_end_num=8)
    complete_assignment(db_session, a4.id, student.id)

    # Total over P2, P3, P4 = 6 videos, 60 mins -> 10.0 min/video.
    # For 5 videos: 5 * 10 = 50 minutes.
    est = estimate_video_duration(db_session, student.id, course.id, video_count=5)
    assert est.is_historical is True
    assert est.average_unit_minutes == 10.0
    assert est.suggested_duration_minutes == 50
    assert est.plans_count == 3

