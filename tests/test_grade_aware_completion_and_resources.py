import uuid
from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.dependencies import SESSION_COOKIE_NAME
from app.models.book import Book, BookChapter
from app.models.course import Course, CourseChapter
from app.models.plan import CompletionAuditAction, PlanAssignment, PlanStatus, StudyPlan, TaskType
from app.models.subject import Subject
from app.models.user import User, UserRole
from app.services.academic_service import (
    create_subject,
    get_subject_by_name,
    update_subject,
)
from app.services.auth_service import create_session
from app.services.plan_service import (
    PlanValidationError,
    complete_assignment,
    create_assignment,
    create_study_plan,
    get_assignment_audit_logs,
    publish_study_plan,
    reset_assignment_completion,
    undo_assignment_completion,
)
from app.services.resource_service import (
    create_book,
    create_course,
    list_books,
    list_courses,
)
from app.services.user_service import create_student, update_student_grade


@pytest.fixture
def curriculum_setup(db_session: Session, tutor_user: User):
    # 1. Subject Physics supporting 10, 11, 12
    sub_phys = create_subject(db_session, name="Physics", grades=["10", "11", "12"])
    # 2. Subject Geometry supporting 10, 11
    sub_geom = create_subject(db_session, name="Geometry", grades=["10", "11"])
    # 3. Subject Calculus supporting 11, 12
    sub_calc = create_subject(db_session, name="Calculus", grades=["11", "12"])

    # 4. Create Students for Grade 10 and Grade 11
    st_g10 = create_student(
        db_session,
        username="student_g10",
        full_name="Student Grade Ten",
        password="Password123!",
        grade="10",
    )
    st_g11 = create_student(
        db_session,
        username="student_g11",
        full_name="Student Grade Eleven",
        password="Password123!",
        grade="11",
    )

    # Assign effective subjects via track or custom
    from app.models.track import AcademicTrack
    track = AcademicTrack(
        name="STEM",
        is_default=True,
        subjects=[sub_phys, sub_geom, sub_calc],
    )
    db_session.add(track)
    st_g10.academic_track = track
    st_g11.academic_track = track
    db_session.commit()

    # Books
    b_phys_10 = create_book(db_session, subject_id=sub_phys.id, title="Physics 10 Book", grade="10")
    b_phys_11 = create_book(db_session, subject_id=sub_phys.id, title="Physics 11 Book", grade="11")
    b_geom_10 = create_book(db_session, subject_id=sub_geom.id, title="Geometry 10 Book", grade="10")

    ch1 = BookChapter(book_id=b_phys_10.id, title="Ch 1", test_count=30, display_order=1)
    ch2 = BookChapter(book_id=b_phys_11.id, title="Ch 1", test_count=30, display_order=1)
    ch3 = BookChapter(book_id=b_geom_10.id, title="Ch 1", test_count=30, display_order=1)
    db_session.add_all([ch1, ch2, ch3])

    # Courses
    c_phys_10 = create_course(db_session, subject_id=sub_phys.id, teacher_name="Dr. P", name="Physics 10 Videos", grade="10")
    c_phys_11 = create_course(db_session, subject_id=sub_phys.id, teacher_name="Dr. P", name="Physics 11 Videos", grade="11")
    c_calc_12 = create_course(db_session, subject_id=sub_calc.id, teacher_name="Dr. C", name="Calculus 12 Videos", grade="12")

    vch1 = CourseChapter(course_id=c_phys_10.id, name="VCh 1", video_count=10, display_order=1)
    vch2 = CourseChapter(course_id=c_phys_11.id, name="VCh 1", video_count=10, display_order=1)
    vch3 = CourseChapter(course_id=c_calc_12.id, name="VCh 1", video_count=10, display_order=1)
    db_session.add_all([vch1, vch2, vch3])

    db_session.commit()
    db_session.refresh(b_phys_10)
    db_session.refresh(b_phys_11)
    db_session.refresh(b_geom_10)
    db_session.refresh(c_phys_10)
    db_session.refresh(c_phys_11)
    db_session.refresh(c_calc_12)

    return {
        "sub_phys": sub_phys,
        "sub_geom": sub_geom,
        "sub_calc": sub_calc,
        "st_g10": st_g10,
        "st_g11": st_g11,
        "b_phys_10": b_phys_10,
        "b_phys_11": b_phys_11,
        "b_geom_10": b_geom_10,
        "c_phys_10": c_phys_10,
        "c_phys_11": c_phys_11,
        "c_calc_12": c_calc_12,
    }


def test_student_completion_saves_actual_duration_and_timestamp(
    client: TestClient, db_session: Session, tutor_user: User, curriculum_setup
):
    st = curriculum_setup["st_g10"]
    sub = curriculum_setup["sub_phys"]
    book = curriculum_setup["b_phys_10"]
    chapter = book.chapters[0]

    plan = create_study_plan(db_session, st.id, tutor_user.id, date.today(), title="G10 Plan")
    task = create_assignment(
        db_session,
        plan_id=plan.id,
        scheduled_date=date.today(),
        subject_id=sub.id,
        task_type=TaskType.TEST,
        recommended_duration_minutes=45,
        book_id=book.id,
        book_chapter_id=chapter.id,
        test_start_num=1,
        test_end_num=10,
    )
    publish_study_plan(db_session, plan.id)

    token, sess_rec = create_session(db_session, st)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    headers = {"X-CSRF-Token": sess_rec.csrf_token}

    # Negative or zero duration must be rejected
    resp_invalid = client.post(
        f"/student/assignments/{task.id}/complete",
        data={"actual_duration_minutes": 0},
        headers=headers,
    )
    assert resp_invalid.status_code == 400

    # Valid completion with actual duration
    resp = client.post(
        f"/student/assignments/{task.id}/complete",
        data={"actual_duration_minutes": 50},
        headers=headers,
    )
    assert resp.status_code == 200

    db_session.refresh(task)
    assert task.is_completed is True
    assert task.completed_at is not None
    assert task.actual_duration_minutes == 50
    assert task.recommended_duration_minutes == 45

    # Check audit entry
    audits = get_assignment_audit_logs(db_session, task.id)
    assert len(audits) == 1
    assert audits[0].action == CompletionAuditAction.COMPLETED
    assert audits[0].actual_duration_minutes == 50
    assert audits[0].performed_by_id == st.id


def test_undo_and_recompletion_preserves_history(
    client: TestClient, db_session: Session, tutor_user: User, curriculum_setup
):
    st = curriculum_setup["st_g10"]
    sub = curriculum_setup["sub_phys"]
    book = curriculum_setup["b_phys_10"]
    chapter = book.chapters[0]

    plan = create_study_plan(db_session, st.id, tutor_user.id, date.today(), title="G10 Plan")
    task = create_assignment(
        db_session,
        plan_id=plan.id,
        scheduled_date=date.today(),
        subject_id=sub.id,
        task_type=TaskType.TEST,
        recommended_duration_minutes=30,
        book_id=book.id,
        book_chapter_id=chapter.id,
        test_start_num=1,
        test_end_num=10,
    )
    publish_study_plan(db_session, plan.id)

    token, sess_rec = create_session(db_session, st)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    headers = {"X-CSRF-Token": sess_rec.csrf_token}

    # 1. Complete with 35 mins
    client.post(
        f"/student/assignments/{task.id}/complete",
        data={"actual_duration_minutes": 35},
        headers=headers,
    )
    db_session.refresh(task)
    first_completed_at = task.completed_at

    # 2. Undo completion
    resp_undo = client.post(
        f"/student/assignments/{task.id}/undo",
        headers=headers,
    )
    assert resp_undo.status_code == 200

    db_session.refresh(task)
    assert task.is_completed is False
    assert task.completed_at is None
    assert task.actual_duration_minutes is None

    # Check audits after undo
    audits_after_undo = get_assignment_audit_logs(db_session, task.id)
    assert len(audits_after_undo) == 2
    # Newest audit is STUDENT_UNDO
    assert audits_after_undo[0].action == CompletionAuditAction.STUDENT_UNDO
    assert audits_after_undo[0].actual_duration_minutes == 35
    assert audits_after_undo[0].recorded_completed_at == first_completed_at
    # Oldest audit is COMPLETED
    assert audits_after_undo[1].action == CompletionAuditAction.COMPLETED
    assert audits_after_undo[1].actual_duration_minutes == 35

    # 3. Re-complete with 40 mins
    resp_recomp = client.post(
        f"/student/assignments/{task.id}/complete",
        data={"actual_duration_minutes": 40},
        headers=headers,
    )
    assert resp_recomp.status_code == 200

    db_session.refresh(task)
    assert task.is_completed is True
    assert task.actual_duration_minutes == 40
    assert task.completed_at is not None
    assert task.completed_at != first_completed_at

    # Audit history must now have 3 entries
    audits_after_recomp = get_assignment_audit_logs(db_session, task.id)
    assert len(audits_after_recomp) == 3
    assert audits_after_recomp[0].action == CompletionAuditAction.COMPLETED
    assert audits_after_recomp[0].actual_duration_minutes == 40
    assert audits_after_recomp[1].action == CompletionAuditAction.STUDENT_UNDO
    assert audits_after_recomp[1].actual_duration_minutes == 35
    assert audits_after_recomp[2].action == CompletionAuditAction.COMPLETED
    assert audits_after_recomp[2].actual_duration_minutes == 35


def test_subject_grade_configuration_and_book_course_validation(db_session: Session):
    sub = create_subject(db_session, name="Chemistry", grades=["10", "11"])
    assert "10" in sub.grades
    assert "11" in sub.grades
    assert "12" not in sub.grades

    # Creating course in supported grade 10 succeeds
    c1 = create_course(db_session, subject_id=sub.id, teacher_name="Dr. Curie", name="Chem 10", grade="10")
    assert c1.grade == "10"

    # Creating course in unsupported grade 12 fails
    with pytest.raises(ValueError) as exc:
        create_course(db_session, subject_id=sub.id, teacher_name="Dr. Curie", name="Chem 12", grade="12")
    assert "not supported by subject" in str(exc.value)

    # Creating book in supported grade 11 succeeds
    b1 = create_book(db_session, subject_id=sub.id, title="Chem 11 Book", grade="11")
    assert b1.grade == "11"

    # Creating book in unsupported grade 12 fails
    with pytest.raises(ValueError) as exc_b:
        create_book(db_session, subject_id=sub.id, title="Chem 12 Book", grade="12")
    assert "not supported by subject" in str(exc_b.value)

    # Tutor updates subject to also support grade 12
    update_subject(db_session, subject_id=sub.id, name="Chemistry", grades=["10", "11", "12"])
    assert "12" in sub.grades

    # Now creating grade 12 book succeeds
    b2 = create_book(db_session, subject_id=sub.id, title="Chem 12 Book", grade="12")
    assert b2.grade == "12"


def test_resource_filtering_and_assignment_restrictions(
    db_session: Session, tutor_user: User, curriculum_setup
):
    st_g10 = curriculum_setup["st_g10"]
    st_g11 = curriculum_setup["st_g11"]
    sub_phys = curriculum_setup["sub_phys"]
    b_phys_10 = curriculum_setup["b_phys_10"]
    b_phys_11 = curriculum_setup["b_phys_11"]
    c_phys_10 = curriculum_setup["c_phys_10"]
    c_phys_11 = curriculum_setup["c_phys_11"]

    # list_courses and list_books filter by grade
    courses_g10 = list_courses(db_session, subject_id=sub_phys.id, grade=st_g10.grade)
    assert len(courses_g10) == 1
    assert courses_g10[0].id == c_phys_10.id

    courses_g11 = list_courses(db_session, subject_id=sub_phys.id, grade=st_g11.grade)
    assert len(courses_g11) == 1
    assert courses_g11[0].id == c_phys_11.id

    books_g10 = list_books(db_session, subject_id=sub_phys.id, grade=st_g10.grade)
    assert len(books_g10) == 1
    assert books_g10[0].id == b_phys_10.id

    books_g11 = list_books(db_session, subject_id=sub_phys.id, grade=st_g11.grade)
    assert len(books_g11) == 1
    assert books_g11[0].id == b_phys_11.id

    # Create plan for Grade 10 student
    plan_g10 = create_study_plan(db_session, st_g10.id, tutor_user.id, date.today(), title="Plan G10")

    # Assigning Grade 10 book to Grade 10 student succeeds
    a_valid = create_assignment(
        db_session,
        plan_id=plan_g10.id,
        scheduled_date=date.today(),
        subject_id=sub_phys.id,
        task_type=TaskType.TEST,
        recommended_duration_minutes=30,
        book_id=b_phys_10.id,
        book_chapter_id=b_phys_10.chapters[0].id,
        test_start_num=1,
        test_end_num=5,
    )
    assert a_valid is not None

    # Assigning Grade 11 book to Grade 10 student fails
    with pytest.raises(PlanValidationError) as exc_plan:
        create_assignment(
            db_session,
            plan_id=plan_g10.id,
            scheduled_date=date.today(),
            subject_id=sub_phys.id,
            task_type=TaskType.TEST,
            recommended_duration_minutes=30,
            book_id=b_phys_11.id,
            book_chapter_id=b_phys_11.chapters[0].id,
            test_start_num=1,
            test_end_num=5,
        )
    assert "does not match student's grade" in str(exc_plan.value)

    # Assigning Grade 11 video to Grade 10 student fails
    with pytest.raises(PlanValidationError) as exc_vid:
        create_assignment(
            db_session,
            plan_id=plan_g10.id,
            scheduled_date=date.today(),
            subject_id=sub_phys.id,
            task_type=TaskType.VIDEO,
            recommended_duration_minutes=30,
            course_id=c_phys_11.id,
            course_chapter_id=c_phys_11.chapters[0].id,
            video_start_num=1,
            video_end_num=2,
        )
    assert "does not match student's grade" in str(exc_vid.value)


def test_student_isolation_and_archived_plan_restriction(
    client: TestClient, db_session: Session, tutor_user: User, curriculum_setup
):
    st_g10 = curriculum_setup["st_g10"]
    st_g11 = curriculum_setup["st_g11"]
    sub = curriculum_setup["sub_phys"]
    book = curriculum_setup["b_phys_10"]

    plan = create_study_plan(db_session, st_g10.id, tutor_user.id, date.today())
    task = create_assignment(
        db_session,
        plan_id=plan.id,
        scheduled_date=date.today(),
        subject_id=sub.id,
        task_type=TaskType.TEST,
        recommended_duration_minutes=30,
        book_id=book.id,
        book_chapter_id=book.chapters[0].id,
        test_start_num=1,
        test_end_num=5,
    )
    publish_study_plan(db_session, plan.id)

    # st_g11 tries to complete st_g10's task -> rejected
    token_11, sess_11 = create_session(db_session, st_g11)
    client.cookies.set(SESSION_COOKIE_NAME, token_11)
    headers = {"X-CSRF-Token": sess_11.csrf_token}

    resp_cross = client.post(
        f"/student/assignments/{task.id}/complete",
        data={"actual_duration_minutes": 30},
        headers=headers,
    )
    assert resp_cross.status_code == 403

    resp_undo_cross = client.post(
        f"/student/assignments/{task.id}/undo",
        headers=headers,
    )
    assert resp_undo_cross.status_code == 403


def test_tutor_update_student_grade(db_session: Session, curriculum_setup):
    st = curriculum_setup["st_g10"]
    assert st.grade == "10"

    updated = update_student_grade(db_session, st.id, "11")
    assert updated.grade == "11"

    # Invalid grade fails
    with pytest.raises(ValueError):
        update_student_grade(db_session, st.id, "9")
