import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Dict

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.core.dependencies import SESSION_COOKIE_NAME
from app.core.timezone import now_utc
from app.models.book import Book, BookChapter
from app.models.course import Course, CourseChapter
from app.models.meeting import MeetingType
from app.models.plan import CompletionAuditLog, PlanStatus, TaskType
from app.models.practice_exam import PracticeExamBooklet, StudentPracticeAttempt, StudentPracticeBookletAttempt
from app.models.user import User
from app.services.academic_service import (
    SubjectInUseError,
    assign_student_track,
    create_subject,
    create_track,
    delete_subject,
)
from app.services.auth_service import create_session
from app.services.exam_service import (
    ExamValidationError,
    archive_exam,
    assign_exam_series_to_students,
    configure_exam_grade_track,
    create_exam,
    create_exam_session,
    get_exam_series_analytics,
    get_student_available_exams,
    submit_student_exam_result,
    tutor_correct_exam_result,
    update_exam_session,
    update_student_exam_result,
)
from app.services.meeting_service import (
    MeetingValidationError,
    create_meeting,
    update_meeting_details,
)
from app.services.message_service import get_or_create_conversation, send_message
from app.services.plan_service import (
    PlanValidationError,
    archive_study_plan,
    complete_assignment,
    create_assignment,
    create_study_plan,
    delete_assignment,
    list_student_plans,
    reorder_assignment,
    reset_assignment_completion,
)
from app.services.practice_exam_service import (
    PracticeExamValidationError,
    add_practice_exam_booklet,
    configure_practice_exam_questions,
    create_practice_exam,
    create_practice_reporting_group,
    get_student_booklet_state,
    start_practice_attempt,
    submit_booklet_answers,
)
from app.services.user_service import create_student


def _setup_practice_fixture(db: Session, is_timed: bool = True):
    sub = create_subject(db, name=f"Sub_{uuid.uuid4().hex[:6]}", grades=["12"])
    track = create_track(db, name=f"Track_{uuid.uuid4().hex[:6]}", subject_ids=[sub.id])
    student_a = create_student(
        db,
        username=f"stu_a_{uuid.uuid4().hex[:6]}",
        full_name="Student A",
        password="Password123!",
        grade="12",
    )
    student_a = assign_student_track(db, student_a.id, track.id)
    student_b = create_student(
        db,
        username=f"stu_b_{uuid.uuid4().hex[:6]}",
        full_name="Student B",
        password="Password123!",
        grade="12",
    )
    student_b = assign_student_track(db, student_b.id, track.id)
    exam = create_practice_exam(
        db,
        title="Timed Practice Exam",
        grade="12",
        academic_track_id=track.id,
        is_timed=is_timed,
    )
    grp = create_practice_reporting_group(db, exam.id, "Section 1")
    b1 = add_practice_exam_booklet(
        db,
        practice_exam_id=exam.id,
        title="Booklet 1",
        pdf_file_path="practice_booklets/dummy.pdf",
        pdf_file_name="dummy.pdf",
        question_start=1,
        question_end=2,
        duration_minutes=10 if is_timed else None,
    )
    configure_practice_exam_questions(
        db,
        exam.id,
        [
            {"question_number": 1, "correct_choice": 2, "subject_id": sub.id, "reporting_group_id": grp.id},
            {"question_number": 2, "correct_choice": 4, "subject_id": sub.id, "reporting_group_id": grp.id},
        ],
    )
    return sub, track, student_a, student_b, exam, grp, b1


# ---------------------------------------------------------------------------
# Practice Exam Security & Business-Logic Regressions
# ---------------------------------------------------------------------------


def test_practice_exam_cross_student_booklet_idor_and_no_timer_mutation(client: TestClient, db_session: Session):
    _, _, student_a, student_b, exam, _, b1 = _setup_practice_fixture(db_session, is_timed=True)
    attempt = start_practice_attempt(db_session, student_a, exam.id)

    # Set Student A's booklet expiration in the past so any unguarded get_student_booklet_state would lock it
    ba = db_session.query(StudentPracticeBookletAttempt).filter(
        StudentPracticeBookletAttempt.attempt_id == attempt.id,
        StudentPracticeBookletAttempt.booklet_id == b1.id,
    ).first()
    assert ba is not None
    ba.expires_at = now_utc() - timedelta(minutes=5)
    db_session.commit()

    # Service check: Student B cannot inspect Student A's attempt and must NOT lock Student A's booklet
    with pytest.raises(PracticeExamValidationError):
        get_student_booklet_state(db_session, attempt.id, b1.id, student_id=student_b.id)
    db_session.refresh(ba)
    assert ba.is_locked is False

    token_b, sess_b = create_session(db_session, student_b)
    client.cookies.set(SESSION_COOKIE_NAME, token_b)

    # HTTP GET booklet runner -> 403, no timer lock
    resp_get = client.get(f"/student/practice-exams/attempts/{attempt.id}/booklets/{b1.id}", follow_redirects=False)
    assert resp_get.status_code == 403
    db_session.refresh(ba)
    assert ba.is_locked is False

    # HTTP POST form save -> 403 (previously 500 or leaked/locked)
    resp_save = client.post(
        f"/student/practice-exams/attempts/{attempt.id}/booklets/{b1.id}/save",
        data={"csrf_token": sess_b.csrf_token, "q_1": "1"},
        follow_redirects=False,
    )
    assert resp_save.status_code == 403
    db_session.refresh(ba)
    assert ba.is_locked is False

    # HTTP POST form submit -> 403
    resp_sub = client.post(
        f"/student/practice-exams/attempts/{attempt.id}/booklets/{b1.id}/submit",
        data={"csrf_token": sess_b.csrf_token, "q_1": "1"},
        follow_redirects=False,
    )
    assert resp_sub.status_code == 403

    # HTTP GET results -> 403 regardless of IN_PROGRESS or COMPLETED (no status oracle)
    resp_res = client.get(f"/student/practice-exams/attempts/{attempt.id}/results", follow_redirects=False)
    assert resp_res.status_code == 403


def test_inactive_practice_exam_blocked_on_start_and_download(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    booklet_dir = tmp_path / "practice_booklets"
    booklet_dir.mkdir(parents=True, exist_ok=True)
    pdf_file = booklet_dir / "dummy.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 test")

    _, _, student_a, _, exam, _, b1 = _setup_practice_fixture(db_session, is_timed=False)

    # Start attempt while active, then deactivate exam
    attempt = start_practice_attempt(db_session, student_a, exam.id)
    exam.is_active = False
    db_session.commit()

    token_a, sess_a = create_session(db_session, student_a)
    client.cookies.set(SESSION_COOKIE_NAME, token_a)

    resp_dl = client.get(
        f"/student/practice-exams/attempts/{attempt.id}/booklets/{b1.id}/download",
        follow_redirects=False,
    )
    assert resp_dl.status_code == 403

    # Also starting fresh attempt on inactive exam must fail cleanly (even via another eligible student)
    with pytest.raises(PracticeExamValidationError):
        start_practice_attempt(db_session, student_a, exam.id)


def test_configure_questions_rejects_foreign_reporting_group_and_atomic_scoring(db_session: Session):
    sub, track, student_a, _, exam, _, b1 = _setup_practice_fixture(db_session, is_timed=False)
    other_exam = create_practice_exam(db_session, title="Other", grade="12", academic_track_id=track.id)
    other_grp = create_practice_reporting_group(db_session, other_exam.id, "Foreign Group")

    with pytest.raises(PracticeExamValidationError):
        configure_practice_exam_questions(
            db_session,
            exam.id,
            [{"question_number": 0, "correct_choice": 1, "subject_id": sub.id}],
        )

    with pytest.raises(PracticeExamValidationError):
        configure_practice_exam_questions(
            db_session,
            exam.id,
            [{"question_number": 1, "correct_choice": 1, "subject_id": sub.id, "reporting_group_id": other_grp.id}],
        )

    attempt = start_practice_attempt(db_session, student_a, exam.id)
    res = submit_booklet_answers(
        db_session,
        student=student_a,
        attempt_id=attempt.id,
        booklet_id=b1.id,
        answers={1: 2, 2: 4},
        advance_to_next=True,
    )
    assert res["completed"] is True
    db_session.refresh(attempt)
    assert attempt.status == "COMPLETED"
    assert attempt.overall_percentage == 100.0
    assert attempt.total_correct == 2


# ---------------------------------------------------------------------------
# Study Plan Isolation, Lifecycle & Hierarchy Regressions
# ---------------------------------------------------------------------------


def test_student_cannot_view_draft_plan_and_history_excludes_drafts(client: TestClient, db_session: Session, tutor_user: User):
    student = create_student(db_session, username="plan_stu", full_name="Plan Student", password="Password123!")
    draft_plan = create_study_plan(db_session, student_id=student.id, tutor_id=tutor_user.id, start_date=date(2026, 11, 1))

    assert list_student_plans(db_session, student.id, exclude_drafts=True) == []

    token, _ = create_session(db_session, student)
    client.cookies.set(SESSION_COOKIE_NAME, token)

    resp_detail = client.get(f"/student/plans/{draft_plan.id}", follow_redirects=False)
    assert resp_detail.status_code == 404

    resp_hist = client.get("/student/plans/history", follow_redirects=False)
    assert resp_hist.status_code == 200
    assert draft_plan.title not in resp_hist.text


def test_study_plan_role_hierarchy_archived_and_reset_guards(db_session: Session, tutor_user: User):
    with pytest.raises(ValueError):
        create_study_plan(db_session, student_id=tutor_user.id, tutor_id=tutor_user.id, start_date=date(2026, 11, 1))

    sub = create_subject(db_session, name="Physics_Plan", grades=["12"])
    track = create_track(db_session, name="Math_Plan", subject_ids=[sub.id])
    student = create_student(
        db_session,
        username="stu_plan_guards",
        full_name="Stu Plan",
        password="Password123!",
        grade="12",
    )
    student = assign_student_track(db_session, student.id, track.id)
    course1 = Course(subject_id=sub.id, teacher_name="T1", name="C1", grade="12")
    course2 = Course(subject_id=sub.id, teacher_name="T2", name="C2", grade="12")
    book1 = Book(subject_id=sub.id, title="B1", grade="12")
    book2 = Book(subject_id=sub.id, title="B2", grade="12")
    db_session.add_all([course1, course2, book1, book2])
    db_session.flush()

    ch_c2 = CourseChapter(course_id=course2.id, name="Other Course Ch", video_count=5, display_order=1)
    ch_c1 = CourseChapter(course_id=course1.id, name="C1 Ch", video_count=5, display_order=1)
    ch_b2 = BookChapter(book_id=book2.id, title="Other Book Ch", test_count=10, display_order=1)
    db_session.add_all([ch_c2, ch_c1, ch_b2])
    db_session.commit()

    plan = create_study_plan(db_session, student_id=student.id, tutor_id=tutor_user.id, start_date=date(2026, 11, 1))

    with pytest.raises(PlanValidationError):
        create_assignment(
            db_session,
            plan_id=plan.id,
            scheduled_date=date(2026, 11, 2),
            subject_id=sub.id,
            task_type=TaskType.VIDEO,
            recommended_duration_minutes=30,
            course_id=course1.id,
            course_chapter_id=ch_c2.id,
            video_start_num=1,
            video_end_num=2,
        )

    with pytest.raises(PlanValidationError):
        create_assignment(
            db_session,
            plan_id=plan.id,
            scheduled_date=date(2026, 11, 2),
            subject_id=sub.id,
            task_type=TaskType.VIDEO,
            recommended_duration_minutes=30,
            course_id=course1.id,
            course_chapter_id=ch_c1.id,
            video_start_num=1,
            video_end_num=8,
        )

    with pytest.raises(PlanValidationError):
        create_assignment(
            db_session,
            plan_id=plan.id,
            scheduled_date=date(2026, 11, 2),
            subject_id=sub.id,
            task_type=TaskType.TEST,
            recommended_duration_minutes=30,
            book_id=book1.id,
            book_chapter_id=ch_b2.id,
        )

    task = create_assignment(
        db_session,
        plan_id=plan.id,
        scheduled_date=date(2026, 11, 2),
        subject_id=sub.id,
        task_type=TaskType.VIDEO,
        recommended_duration_minutes=30,
        course_id=course1.id,
        course_chapter_id=ch_c1.id,
        video_start_num=1,
        video_end_num=2,
    )

    # Resetting a pending task must fail and NOT create an audit log
    with pytest.raises(PlanValidationError):
        reset_assignment_completion(db_session, task.id, tutor_id=tutor_user.id)
    assert db_session.query(CompletionAuditLog).filter(CompletionAuditLog.assignment_id == task.id).count() == 0

    archive_study_plan(db_session, plan.id, tutor_id=tutor_user.id)
    with pytest.raises(PlanValidationError):
        reorder_assignment(db_session, task.id, "up", tutor_id=tutor_user.id)
    with pytest.raises(PlanValidationError):
        delete_assignment(db_session, task.id, tutor_id=tutor_user.id)


# ---------------------------------------------------------------------------
# External Exam Eligibility, Validation, Analytics & Upload Atomicity
# ---------------------------------------------------------------------------


def _setup_external_exam_fixture(db: Session):
    sub_math = create_subject(db, name=f"Math_{uuid.uuid4().hex[:6]}", grades=["12"])
    sub_bio = create_subject(db, name=f"Bio_{uuid.uuid4().hex[:6]}", grades=["12"])
    track_math = create_track(db, name=f"MathTrack_{uuid.uuid4().hex[:6]}", subject_ids=[sub_math.id])
    track_bio = create_track(db, name=f"BioTrack_{uuid.uuid4().hex[:6]}", subject_ids=[sub_bio.id])

    eligible_student = create_student(
        db,
        username=f"elig_{uuid.uuid4().hex[:6]}",
        full_name="Eligible",
        password="Password123!",
        grade="12",
    )
    eligible_student = assign_student_track(db, eligible_student.id, track_math.id)
    ineligible_student = create_student(
        db,
        username=f"inelig_{uuid.uuid4().hex[:6]}",
        full_name="Ineligible",
        password="Password123!",
        grade="12",
    )
    ineligible_student = assign_student_track(db, ineligible_student.id, track_bio.id)

    exam = create_exam(db, title="Series 1")
    cfg_math = configure_exam_grade_track(
        db,
        exam.id,
        grade="12",
        track_id=track_math.id,
        reporting_groups_data=[{"title": "Math Group", "subject_ids": [sub_math.id]}],
    )
    session = create_exam_session(
        db,
        exam_id=exam.id,
        exam_date=date(2026, 11, 10),
        track_subjects_map={track_math.id: [sub_math.id]},
    )
    return sub_math, sub_bio, track_math, track_bio, eligible_student, ineligible_student, exam, cfg_math, session


def test_external_exam_eligibility_validation_nan_update_and_archived(db_session: Session, tutor_user: User):
    sub_math, sub_bio, track_math, _, elig, inelig, exam, cfg_math, session = _setup_external_exam_fixture(db_session)

    # Track/grade eligibility bypass check: bio student must not submit to math-only session
    with pytest.raises(ExamValidationError):
        submit_student_exam_result(
            db_session,
            student=inelig,
            exam_session_id=session.id,
            group_data=[{"reporting_group_id": cfg_math.reporting_groups[0].id, "group_title": "Forged", "percentage": 50.0}],
        )

    # Forged reporting_group_id rejected
    other_exam = create_exam(db_session, title="Other Exam")
    other_cfg = configure_exam_grade_track(
        db_session,
        other_exam.id,
        grade="12",
        track_id=track_math.id,
        reporting_groups_data=[{"title": "Foreign RG", "subject_ids": [sub_math.id]}],
    )
    with pytest.raises(ExamValidationError):
        submit_student_exam_result(
            db_session,
            student=elig,
            exam_session_id=session.id,
            group_data=[{"reporting_group_id": other_cfg.reporting_groups[0].id, "group_title": "Foreign", "percentage": 75.0}],
        )

    # NaN / Inf / out-of-range percentage rejected
    for bad_pct in [float("nan"), float("inf"), -1.0, 100.1]:
        with pytest.raises(ExamValidationError):
            submit_student_exam_result(
                db_session,
                student=elig,
                exam_session_id=session.id,
                group_data=[{"reporting_group_id": cfg_math.reporting_groups[0].id, "group_title": "Math Group", "percentage": bad_pct}],
            )

    # Valid submission with subject_data
    res = submit_student_exam_result(
        db_session,
        student=elig,
        exam_session_id=session.id,
        subject_data=[{"subject_id": sub_math.id, "correct_answers": 10, "incorrect_answers": 2, "percentage": 80.0}],
        overall_rank=5,
    )

    # update_student_exam_result validation
    with pytest.raises(ExamValidationError):
        update_student_exam_result(
            db_session,
            student=elig,
            result_id=res.id,
            subject_data=[{"subject_id": sub_math.id, "correct_answers": -1, "incorrect_answers": 0, "percentage": 50.0}],
        )
    with pytest.raises(ExamValidationError):
        update_student_exam_result(
            db_session,
            student=elig,
            result_id=res.id,
            subject_data=[{"subject_id": sub_bio.id, "correct_answers": 5, "incorrect_answers": 0, "percentage": 50.0}],
        )
    with pytest.raises(ExamValidationError):
        update_student_exam_result(
            db_session,
            student=elig,
            result_id=res.id,
            subject_data=[
                {"subject_id": sub_math.id, "correct_answers": 5, "incorrect_answers": 0, "percentage": 50.0},
                {"subject_id": sub_math.id, "correct_answers": 6, "incorrect_answers": 0, "percentage": 60.0},
            ],
        )

    # tutor_correct_exam_result validation
    with pytest.raises(ExamValidationError):
        tutor_correct_exam_result(db_session, result_id=res.id, actor_id=tutor_user.id, overall_rank=0)
    with pytest.raises(ExamValidationError):
        tutor_correct_exam_result(
            db_session,
            result_id=res.id,
            actor_id=tutor_user.id,
            group_data=[{"group_title": "Math Group", "percentage": 150.0}],
        )

    # update_exam_session (regression for NameError on series_assignments)
    assign_exam_series_to_students(db_session, exam.id, [elig.id])
    updated_sess = update_exam_session(
        db_session,
        session_id=session.id,
        exam_date=date(2026, 11, 11),
        title="Updated Occurrence",
    )
    assert updated_sess.title == "Updated Occurrence"

    # Archiving exam blocks new edits and hides unsubmitted upcoming occurrences while keeping submitted result in past
    sess_future = create_exam_session(
        db_session,
        exam_id=exam.id,
        exam_date=date(2099, 1, 1),
        track_subjects_map={track_math.id: [sub_math.id]},
    )
    archive_exam(db_session, exam.id, actor_id=tutor_user.id)

    avail = get_student_available_exams(db_session, elig)
    assert all(item["session"].id != sess_future.id for item in avail["upcoming"])
    assert any(item["session"].id == session.id for item in avail["past"])

    with pytest.raises(ExamValidationError):
        update_student_exam_result(db_session, student=elig, result_id=res.id, overall_rank=3)


def test_exam_series_analytics_submission_rate_capped(db_session: Session):
    sub_math, _, track_math, _, elig, _, exam, cfg_math, sess_past = _setup_external_exam_fixture(db_session)
    sess_future = create_exam_session(
        db_session,
        exam_id=exam.id,
        exam_date=date(2099, 5, 1),
        track_subjects_map={track_math.id: [sub_math.id]},
    )
    # Only past session is assigned, yet student submits for both past AND future (pre-submission)
    assign_exam_series_to_students(db_session, exam.id, [elig.id])
    submit_student_exam_result(
        db_session,
        student=elig,
        exam_session_id=sess_past.id,
        group_data=[{"reporting_group_id": cfg_math.reporting_groups[0].id, "group_title": "Math Group", "percentage": 90.0}],
    )
    submit_student_exam_result(
        db_session,
        student=elig,
        exam_session_id=sess_future.id,
        group_data=[{"reporting_group_id": cfg_math.reporting_groups[0].id, "group_title": "Math Group", "percentage": 95.0}],
    )
    analytics = get_exam_series_analytics(db_session, exam.id)
    assert analytics["submission_rate"] <= 100.0
    assert analytics["submission_rate"] == 100.0
    assert analytics["missing_submissions"] == 0


def test_uploads_leave_no_orphaned_files_on_validation_error(
    client: TestClient, db_session: Session, tutor_session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))

    # 1. Student external exam invalid numeric score + valid PDF -> 400 and NO file left on disk
    sub_math, _, _, _, elig, _, _, _, session = _setup_external_exam_fixture(db_session)
    token_s, sess_s = create_session(db_session, elig)
    client.cookies.set(SESSION_COOKIE_NAME, token_s)
    resp_s = client.post(
        f"/student/exams/{session.id}/submit",
        data={
            "csrf_token": sess_s.csrf_token,
            f"correct_{sub_math.id}": "abc",
            f"incorrect_{sub_math.id}": "0",
            f"percentage_{sub_math.id}": "80",
        },
        files={"report_card_file": ("card.pdf", b"%PDF-1.4\ntest", "application/pdf")},
        follow_redirects=False,
    )
    assert resp_s.status_code == 400
    assert (list((tmp_path / "report_cards").glob("*")) if (tmp_path / "report_cards").exists() else []) == []

    # 2. Tutor historical exam invalid date + valid PDF -> 400 and NO file left on disk
    token_t, sess_t = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, token_t)
    resp_h = client.post(
        "/tutor/historical-exams/create",
        data={
            "csrf_token": sess_t.csrf_token,
            "student_id": str(elig.id),
            "exam_name": "Bad Hist",
            "exam_date": "not-a-date",
        },
        files={"report_card_file": ("hist.pdf", b"%PDF-1.4\ntest", "application/pdf")},
        follow_redirects=False,
    )
    assert resp_h.status_code == 400
    assert (list((tmp_path / "report_cards").glob("*")) if (tmp_path / "report_cards").exists() else []) == []

    # 3. Tutor practice exam invalid booklet range + valid PDF -> unlinks uploaded file
    _, track_p, _, _, p_exam, _, _ = _setup_practice_fixture(db_session, is_timed=False)
    resp_p = client.post(
        f"/tutor/practice-exams/{p_exam.id}/booklets",
        data={
            "csrf_token": sess_t.csrf_token,
            "title": "Overlapping Booklet",
            "question_start": "1",
            "question_end": "2",
        },
        files={"file": ("booklet.pdf", b"%PDF-1.4\ntest", "application/pdf")},
        follow_redirects=False,
    )
    assert resp_p.status_code == 303
    assert "err=" in resp_p.headers["location"]
    assert (list((tmp_path / "practice_booklets").glob("*")) if (tmp_path / "practice_booklets").exists() else []) == []


# ---------------------------------------------------------------------------
# Academic Deletion, Chat Pagination, Meeting URL, Malformed Inputs & Config
# ---------------------------------------------------------------------------


def test_delete_subject_blocks_plan_or_exam_references(db_session: Session, tutor_user: User):
    sub = create_subject(db_session, name=f"RefSub_{uuid.uuid4().hex[:6]}", grades=["12"])
    student = create_student(db_session, username="ref_stu", full_name="Ref Stu", password="Password123!", grade="12")
    plan = create_study_plan(db_session, student_id=student.id, tutor_id=tutor_user.id, start_date=date(2026, 11, 1))
    create_assignment(
        db_session,
        plan_id=plan.id,
        scheduled_date=date(2026, 11, 2),
        subject_id=sub.id,
        task_type=TaskType.CUSTOM,
        recommended_duration_minutes=30,
        title="Study",
    )
    with pytest.raises(SubjectInUseError):
        delete_subject(db_session, sub.id)


def test_chat_pagination_encodes_plus_sign(
    client: TestClient, db_session: Session, tutor_user: User, monkeypatch: pytest.MonkeyPatch
):
    from types import SimpleNamespace
    import app.routers.student_chat as student_chat_mod
    import app.routers.tutor_messages as tutor_messages_mod

    student = create_student(db_session, username="chat_stu", full_name="Chat Student", password="Password123!")
    conv = get_or_create_conversation(db_session, student.id, tutor_id=tutor_user.id)
    base_ts = now_utc() - timedelta(minutes=40)
    for idx in range(35):
        m_obj = send_message(db_session, conv.id, student, f"Msg {idx}", commit=False)
        m_obj.created_at = base_ts + timedelta(seconds=idx)
    db_session.commit()

    token_s, _ = create_session(db_session, student)
    client.cookies.set(SESSION_COOKIE_NAME, token_s)
    future_ts = (now_utc() + timedelta(minutes=5)).isoformat()
    resp_s = client.get("/student/chat/older", params={"before": future_ts})
    assert resp_s.status_code == 200
    m = re.search(r'hx-get="([^"]+)"', resp_s.text)
    assert m is not None
    assert "+" not in m.group(1) and "%3A" in m.group(1)
    assert client.get(m.group(1)).status_code == 200

    # Simulate timezone-aware PostgreSQL DateTime (+00:00) to confirm '+' is percent-encoded as %2B
    tz_msg = SimpleNamespace(
        id=uuid.uuid4(),
        sender_id=student.id,
        sender=student,
        content="TZ aware",
        created_at=datetime(2026, 11, 25, 20, 0, 0, tzinfo=timezone.utc),
        is_read=True,
        read_at=None,
    )
    orig_list = student_chat_mod.list_messages
    monkeypatch.setattr(student_chat_mod, "list_messages", lambda *a, **kw: ([tz_msg], True))
    resp_tz = client.get("/student/chat/older", params={"before": future_ts})
    assert resp_tz.status_code == 200
    m_tz = re.search(r'hx-get="([^"]+)"', resp_tz.text)
    assert m_tz is not None
    assert "%2B00%3A00" in m_tz.group(1)
    monkeypatch.setattr(student_chat_mod, "list_messages", orig_list)

    token_t, _ = create_session(db_session, tutor_user)
    client.cookies.set(SESSION_COOKIE_NAME, token_t)
    resp_t = client.get(f"/tutor/messages/{conv.id}/older", params={"before": future_ts})
    assert resp_t.status_code == 200
    m2 = re.search(r'hx-get="([^"]+)"', resp_t.text)
    assert m2 is not None
    assert "+" not in m2.group(1) and "%3A" in m2.group(1)
    assert client.get(m2.group(1)).status_code == 200

    monkeypatch.setattr(tutor_messages_mod, "list_messages", lambda *a, **kw: ([tz_msg], True))
    resp_tz2 = client.get(f"/tutor/messages/{conv.id}/older", params={"before": future_ts})
    assert resp_tz2.status_code == 200
    m_tz2 = re.search(r'hx-get="([^"]+)"', resp_tz2.text)
    assert m_tz2 is not None
    assert "%2B00%3A00" in m_tz2.group(1)


def test_meeting_url_rejects_non_http_schemes(db_session: Session, tutor_user: User):
    student = create_student(db_session, username="meet_stu", full_name="Meet Stu", password="Password123!")
    with pytest.raises(MeetingValidationError):
        create_meeting(
            db_session,
            tutor=tutor_user,
            student_id=student.id,
            meeting_date=date(2026, 12, 1),
            start_time_obj=time(10, 0),
            duration_minutes=45,
            meeting_type=MeetingType.ONLINE,
            meeting_url="javascript:alert(1)",
        )

    meeting = create_meeting(
        db_session,
        tutor=tutor_user,
        student_id=student.id,
        meeting_date=date(2026, 12, 1),
        start_time_obj=time(10, 0),
        duration_minutes=45,
        meeting_type=MeetingType.ONLINE,
        meeting_url="https://meet.example.com/room-1",
    )
    with pytest.raises(MeetingValidationError):
        update_meeting_details(
            db_session,
            meeting_id=meeting.id,
            tutor=tutor_user,
            meeting_url="data:text/html,<script>alert(1)</script>",
        )


def test_malformed_tutor_form_dates_return_400_not_500(client: TestClient, db_session: Session, tutor_user: User, tutor_session):
    token_t, sess_t = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, token_t)

    resp_exam = client.post(
        "/tutor/exams/create",
        data={
            "csrf_token": sess_t.csrf_token,
            "title": "Test",
            "first_exam_date": "bad-date",
        },
        follow_redirects=False,
    )
    assert resp_exam.status_code == 400

    resp_sched = client.post(
        "/tutor/scheduler/generate",
        data={
            "csrf_token": sess_t.csrf_token,
            "target_week_start": "bad-date",
        },
        follow_redirects=False,
    )
    assert resp_sched.status_code == 400

    student = create_student(db_session, username="bad_plan_stu", full_name="Bad Plan", password="Password123!")
    sub = create_subject(db_session, name="BadPlanSub", grades=["12"])
    plan = create_study_plan(db_session, student_id=student.id, tutor_id=tutor_user.id, start_date=date(2026, 11, 1))
    resp_plan = client.post(
        f"/tutor/plans/{plan.id}/assignments",
        data={
            "csrf_token": sess_t.csrf_token,
            "scheduled_date": "invalid-date",
            "subject_id": str(sub.id),
            "task_type": "CUSTOM",
            "recommended_duration_minutes": "30",
        },
        follow_redirects=False,
    )
    assert resp_plan.status_code == 400


def test_settings_debug_defaults_false_and_prod_disables_docs():
    import os
    import subprocess
    import sys

    default_cfg = Settings(_env_file=None)
    assert default_cfg.DEBUG is False

    env = os.environ.copy()
    env["ENVIRONMENT"] = "production"
    out = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "from app.main import app; print(app.docs_url, app.redoc_url, app.openapi_url)",
        ],
        env=env,
        text=True,
    ).strip()
    assert out == "None None None"
