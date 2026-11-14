import uuid
from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.dependencies import SESSION_COOKIE_NAME
from app.models.book import Book, BookChapter
from app.models.course import Course, CourseChapter
from app.models.plan import PlanAssignment, PlanStatus, StudyPlan, TaskType
from app.models.session import UserSession
from app.models.subject import Subject
from app.models.track import AcademicTrack
from app.models.user import User, UserRole
from app.services.academic_service import (
    assign_student_track,
    create_subject,
    create_track,
    customize_student_subjects,
    set_track_subjects,
)
from app.services.auth_service import create_session
from app.services.plan_service import (
    complete_assignment,
    create_assignment,
    create_study_plan,
    get_study_plan,
    publish_study_plan,
)
from app.services.user_service import create_student


@pytest.fixture
def test_setup(db_session: Session, tutor_user: User):
    """Setup academic curriculum, tracks, and two students (one track, one custom)."""
    sub_math = create_subject(db_session, "Math")
    sub_phys = create_subject(db_session, "Physics")
    sub_chem = create_subject(db_session, "Chemistry")

    track = create_track(db_session, "Science Track", "Science subjects")
    set_track_subjects(db_session, track.id, [sub_math.id, sub_phys.id])

    # Student 1 with Science Track (Math & Physics)
    st1 = create_student(db_session, "student_one", "Pass123!", "Student One", "st1@valhalla.local")
    assign_student_track(db_session, st1.id, track.id)

    # Student 2 with Customized Subjects (Math & Chemistry)
    st2 = create_student(db_session, "student_two", "Pass123!", "Student Two", "st2@valhalla.local")
    customize_student_subjects(db_session, st2.id, [sub_math.id, sub_chem.id])

    # Books & Courses
    book_phys = Book(subject_id=sub_phys.id, title="Physics Book A", grade="12")
    course_math = Course(subject_id=sub_math.id, teacher_name="Dr. Euler", name="Math Course A", grade="12")
    db_session.add_all([book_phys, course_math])
    db_session.commit()

    bch_phys = BookChapter(book_id=book_phys.id, title="Ch 1 Mechanics", test_count=50, display_order=1)
    cch_math = CourseChapter(course_id=course_math.id, name="Ch 1 Functions", video_count=15, display_order=1)
    db_session.add_all([bch_phys, cch_math])
    db_session.commit()

    return {
        "math": sub_math,
        "phys": sub_phys,
        "chem": sub_chem,
        "track": track,
        "st1": st1,
        "st2": st2,
        "book_phys": book_phys,
        "bch_phys": bch_phys,
        "course_math": course_math,
        "cch_math": cch_math,
    }


def test_tutor_create_plan_and_subject_columns(client: TestClient, db_session: Session, tutor_user: User, tutor_session, test_setup):
    raw_token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)
    st1 = test_setup["st1"]
    st2 = test_setup["st2"]

    # 1. Tutor creates 14-day draft plan for student 1
    start_date_str = "2026-11-15"
    resp = client.post(
        f"/tutor/students/{st1.id}/plans",
        data={"start_date": start_date_str, "title": "Sprint 1", "csrf_token": session_rec.csrf_token},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    plan1_url = resp.headers["location"]

    # Open plan 1 view: Student 1 has Science Track -> Math & Physics
    resp_plan1 = client.get(plan1_url)
    assert resp_plan1.status_code == 200
    assert "Math" in resp_plan1.text
    assert "Physics" in resp_plan1.text
    assert "Chemistry" not in resp_plan1.text
    assert "Sprint 1" in resp_plan1.text
    assert "Draft Plan" in resp_plan1.text

    # 2. Tutor creates plan for student 2 (Customized subjects: Math & Chem)
    resp2 = client.post(
        f"/tutor/students/{st2.id}/plans",
        data={"start_date": start_date_str, "title": "Student 2 Custom Plan", "csrf_token": session_rec.csrf_token},
        follow_redirects=False,
    )
    assert resp2.status_code == 303
    plan2_url = resp2.headers["location"]

    resp_plan2 = client.get(plan2_url)
    assert resp_plan2.status_code == 200
    assert "Math" in resp_plan2.text
    assert "Chemistry" in resp_plan2.text
    assert "Physics" not in resp_plan2.text


def test_tutor_create_tasks_and_validation(client: TestClient, db_session: Session, tutor_user: User, tutor_session, test_setup):
    raw_token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)
    st1 = test_setup["st1"]
    sub_math = test_setup["math"]
    sub_phys = test_setup["phys"]
    book_phys = test_setup["book_phys"]
    bch_phys = test_setup["bch_phys"]
    course_math = test_setup["course_math"]
    cch_math = test_setup["cch_math"]

    plan = create_study_plan(db_session, st1.id, tutor_user.id, date(2026, 11, 15))

    # 1. Add Custom Assignment
    resp_custom = client.post(
        f"/tutor/plans/{plan.id}/assignments",
        data={
            "csrf_token": session_rec.csrf_token,
            "scheduled_date": "2026-11-15",
            "subject_id": str(sub_math.id),
            "task_type": "CUSTOM",
            "title": "Review Formula Sheets",
            "recommended_duration_minutes": 45,
            "description": "Pages 1-10",
        },
        follow_redirects=False,
    )
    assert resp_custom.status_code == 303

    # 2. Add Test Assignment with valid range (1 to 20, max available 50)
    resp_test = client.post(
        f"/tutor/plans/{plan.id}/assignments",
        data={
            "csrf_token": session_rec.csrf_token,
            "scheduled_date": "2026-11-16",
            "subject_id": str(sub_phys.id),
            "task_type": "TEST",
            "book_id": str(book_phys.id),
            "book_chapter_id": str(bch_phys.id),
            "test_start_num": 1,
            "test_end_num": 20,
            "recommended_duration_minutes": 60,
        },
        follow_redirects=False,
    )
    assert resp_test.status_code == 303

    # 3. Add Test Assignment exceeding available test count (available is 50, test_end_num = 60) -> 400 Bad Request
    resp_invalid_test = client.post(
        f"/tutor/plans/{plan.id}/assignments",
        data={
            "csrf_token": session_rec.csrf_token,
            "scheduled_date": "2026-11-16",
            "subject_id": str(sub_phys.id),
            "task_type": "TEST",
            "book_id": str(book_phys.id),
            "book_chapter_id": str(bch_phys.id),
            "test_start_num": 1,
            "test_end_num": 60,
            "recommended_duration_minutes": 60,
        },
        follow_redirects=False,
    )
    assert resp_invalid_test.status_code == 400
    assert "exceeds available tests" in resp_invalid_test.text

    # 4. Add Video Assignment
    resp_video = client.post(
        f"/tutor/plans/{plan.id}/assignments",
        data={
            "csrf_token": session_rec.csrf_token,
            "scheduled_date": "2026-11-17",
            "subject_id": str(sub_math.id),
            "task_type": "VIDEO",
            "course_id": str(course_math.id),
            "course_chapter_id": str(cch_math.id),
            "video_start_num": 1,
            "video_end_num": 3,
            "recommended_duration_minutes": 90,
        },
        follow_redirects=False,
    )
    assert resp_video.status_code == 303


def test_historical_estimate_endpoints_and_totals(client: TestClient, db_session: Session, tutor_user: User, tutor_session, test_setup):
    raw_token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)
    st1 = test_setup["st1"]
    sub_math = test_setup["math"]
    sub_phys = test_setup["phys"]
    book_phys = test_setup["book_phys"]
    bch_phys = test_setup["bch_phys"]
    course_math = test_setup["course_math"]
    cch_math = test_setup["cch_math"]

    # Seed past completed assignments:
    # 20 tests from Physics Book A with 60 minutes duration (3.0 min/test)
    past_plan = create_study_plan(db_session, st1.id, tutor_user.id, date(2026, 10, 1))
    t1 = create_assignment(
        db_session, past_plan.id, date(2026, 10, 1), sub_phys.id, TaskType.TEST, 60,
        book_id=book_phys.id, book_chapter_id=bch_phys.id, test_start_num=1, test_end_num=20
    )
    complete_assignment(db_session, t1.id, st1.id)

    # 10 videos from Math Course A with 150 minutes duration (15.0 min/video)
    v1 = create_assignment(
        db_session, past_plan.id, date(2026, 10, 2), sub_math.id, TaskType.VIDEO, 150,
        course_id=course_math.id, course_chapter_id=cch_math.id, video_start_num=1, video_end_num=10
    )
    complete_assignment(db_session, v1.id, st1.id)

    # New plan
    new_plan = create_study_plan(db_session, st1.id, tutor_user.id, date(2026, 11, 15))

    # Test estimate endpoint for 10 tests: 10 * 3.0 = 30 minutes!
    resp_est_test = client.get(
        f"/tutor/plans/{new_plan.id}/estimate-test?book_id={book_phys.id}&test_start=1&test_end=10"
    )
    assert resp_est_test.status_code == 200
    assert "Historical Estimate:" in resp_est_test.text
    assert "30 minutes" in resp_est_test.text
    assert "3.0 min/test" in resp_est_test.text

    # Video estimate endpoint for 4 videos: 4 * 15.0 = 60 minutes!
    resp_est_video = client.get(
        f"/tutor/plans/{new_plan.id}/estimate-video?course_id={course_math.id}&video_count=4"
    )
    assert resp_est_video.status_code == 200
    assert "Historical Estimate:" in resp_est_video.text
    assert "60 minutes" in resp_est_video.text
    assert "15.0 min/video" in resp_est_video.text

    # Add assignments to new plan: 30m test and 60m video
    create_assignment(
        db_session, new_plan.id, date(2026, 11, 15), sub_phys.id, TaskType.TEST, 30,
        book_id=book_phys.id, book_chapter_id=bch_phys.id, test_start_num=1, test_end_num=10,
        is_estimated=True, estimated_duration_minutes=30
    )
    create_assignment(
        db_session, new_plan.id, date(2026, 11, 15), sub_math.id, TaskType.VIDEO, 60,
        course_id=course_math.id, course_chapter_id=cch_math.id, video_start_num=1, video_end_num=4,
        is_estimated=True, estimated_duration_minutes=60
    )

    # Check totals in planner view: Day 1 total = 90 mins (1 hour 30 minutes)
    resp_planner = client.get(f"/tutor/plans/{new_plan.id}")
    assert resp_planner.status_code == 200
    assert "1 hour 30 minutes" in resp_planner.text
    assert "90 minutes" in resp_planner.text or "1 hour 30 minutes" in resp_planner.text

    # Publish plan
    resp_pub = client.post(
        f"/tutor/plans/{new_plan.id}/publish",
        data={"csrf_token": session_rec.csrf_token},
        follow_redirects=False,
    )
    assert resp_pub.status_code == 303
    db_session.refresh(new_plan)
    assert new_plan.status == PlanStatus.PUBLISHED

    # Archive plan
    resp_arch = client.post(
        f"/tutor/plans/{new_plan.id}/archive",
        data={"csrf_token": session_rec.csrf_token},
        follow_redirects=False,
    )
    assert resp_arch.status_code == 303
    db_session.refresh(new_plan)
    assert new_plan.status == PlanStatus.ARCHIVED


def test_student_experience_and_authorization(client: TestClient, db_session: Session, tutor_user: User, test_setup):
    st1 = test_setup["st1"]
    st2 = test_setup["st2"]
    sub_math = test_setup["math"]

    # Student 1 session
    st1_token, st1_session = create_session(db_session, st1)
    # Student 2 session
    st2_token, st2_session = create_session(db_session, st2)

    # 1. When plan is in DRAFT status, student cannot see it on /student/plan
    draft_plan = create_study_plan(db_session, st1.id, tutor_user.id, date(2026, 11, 15))
    task1 = create_assignment(
        db_session, draft_plan.id, date(2026, 11, 15), sub_math.id, TaskType.CUSTOM, 45, title="Draft Task"
    )

    client.cookies.set(SESSION_COOKIE_NAME, st1_token)
    resp_student_draft = client.get("/student/plan")
    assert resp_student_draft.status_code == 200
    assert "No Active Study Plan Yet" in resp_student_draft.text
    assert "Draft Task" not in resp_student_draft.text

    # 2. Tutor publishes the plan
    publish_study_plan(db_session, draft_plan.id)

    # Now student sees the published 14-day timetable
    resp_student_pub = client.get("/student/plan")
    assert resp_student_pub.status_code == 200
    assert "Draft Task" in resp_student_pub.text
    assert "45m" in resp_student_pub.text
    assert "Mark Complete" in resp_student_pub.text

    # 3. Student completes task with one click
    resp_complete = client.post(
        f"/student/assignments/{task1.id}/complete",
        headers={"X-CSRF-Token": st1_session.csrf_token, "HX-Request": "true"},
    )
    assert resp_complete.status_code == 200
    assert "Completed" in resp_complete.text

    db_session.refresh(task1)
    assert task1.is_completed is True
    assert task1.completed_at is not None

    # 4. Student 2 tries to complete Student 1's task -> 403 Forbidden
    client.cookies.set(SESSION_COOKIE_NAME, st2_token)
    resp_tamper = client.post(
        f"/student/assignments/{task1.id}/complete",
        headers={"X-CSRF-Token": st2_session.csrf_token},
    )
    assert resp_tamper.status_code == 403

    # 5. Student tries to access tutor planning endpoint -> 403 Forbidden
    resp_tutor_forbidden = client.get(f"/tutor/plans/{draft_plan.id}")
    assert resp_tutor_forbidden.status_code == 403


def test_assignment_edit_move_reorder_delete(client: TestClient, db_session: Session, tutor_user: User, tutor_session, test_setup):
    raw_token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)
    st1 = test_setup["st1"]
    sub_math = test_setup["math"]
    sub_phys = test_setup["phys"]

    plan = create_study_plan(db_session, st1.id, tutor_user.id, date(2026, 11, 15))
    task1 = create_assignment(
        db_session, plan.id, date(2026, 11, 15), sub_math.id, TaskType.CUSTOM, 45, title="Task A"
    )
    task2 = create_assignment(
        db_session, plan.id, date(2026, 11, 15), sub_math.id, TaskType.CUSTOM, 60, title="Task B"
    )

    # 1. Edit task
    resp_edit = client.post(
        f"/tutor/plans/assignments/{task1.id}/edit",
        data={
            "csrf_token": session_rec.csrf_token,
            "title": "Task A Updated",
            "recommended_duration_minutes": 55,
            "description": "Updated notes",
        },
        follow_redirects=False,
    )
    assert resp_edit.status_code == 303
    db_session.refresh(task1)
    assert task1.title == "Task A Updated"
    assert task1.recommended_duration_minutes == 55

    # 2. Reorder task (move Task B up)
    resp_reorder = client.post(
        f"/tutor/plans/assignments/{task2.id}/reorder",
        data={"csrf_token": session_rec.csrf_token, "direction": "up"},
        follow_redirects=False,
    )
    assert resp_reorder.status_code == 303

    # 3. Move task to another day and subject
    resp_move = client.post(
        f"/tutor/plans/assignments/{task1.id}/move",
        data={
            "csrf_token": session_rec.csrf_token,
            "new_date": "2026-11-18",
            "new_subject_id": str(sub_phys.id),
        },
        follow_redirects=False,
    )
    assert resp_move.status_code == 303
    db_session.refresh(task1)
    assert task1.scheduled_date == date(2026, 11, 18)
    assert task1.subject_id == sub_phys.id

    # 4. Delete task
    resp_delete = client.post(
        f"/tutor/plans/assignments/{task1.id}/delete",
        data={"csrf_token": session_rec.csrf_token},
        follow_redirects=False,
    )
    assert resp_delete.status_code == 303
    assert db_session.query(PlanAssignment).filter(PlanAssignment.id == task1.id).first() is None
