import uuid
from datetime import date, datetime, time, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.dependencies import SESSION_COOKIE_NAME
from app.core.timezone import get_timezone
from app.models.exam import ExamAuditLog
from app.services.academic_service import (
    assign_student_track,
    create_subject,
    create_track,
    set_track_subjects,
)
from app.services.auth_service import create_session
from app.services.exam_service import (
    ExamValidationError,
    assign_exam_series_to_students,
    configure_exam_grade_track,
    create_exam,
    create_exam_session,
    get_bulk_series_submission_overview,
    get_student_available_exams,
    get_student_exam_analytics,
    get_student_exam_result_by_id,
    get_tutor_session_analytics,
    get_tutor_student_analytics,
    submit_student_exam_result,
    tutor_correct_exam_result,
    update_exam_session,
)
from app.services.user_service import create_student


def _setup_curriculum(db: Session):
    sub_bio = create_subject(db, name="زیست‌شناسی", grades=["10", "11", "12"])
    sub_chem = create_subject(db, name="شیمی", grades=["10", "11", "12"])
    track_tajrobi = create_track(db, name="تجربی")
    set_track_subjects(db, track_tajrobi.id, [sub_bio.id, sub_chem.id])
    return sub_bio, sub_chem, track_tajrobi


def test_reporting_group_analytics_and_session_table(
    db_session: Session,
    client: TestClient,
    tutor_user,
    tutor_session,
):
    sub_bio, sub_chem, track_tajrobi = _setup_curriculum(db_session)
    st12 = create_student(
        db_session,
        username="st12_rg",
        full_name="Student Grade 12",
        password="Password123!",
        grade="12",
    )
    assign_student_track(db_session, st12.id, track_tajrobi.id)

    exam = create_exam(db_session, title="آزمون قلم‌چی", submission_days_after_exam=2)
    gtc = configure_exam_grade_track(
        db_session,
        exam_id=exam.id,
        grade="12",
        track_id=track_tajrobi.id,
        groups_map={"زیست و شیمی": [sub_bio.id, sub_chem.id]},
    )
    rg = gtc.reporting_groups[0]
    session = create_exam_session(
        db_session,
        exam_id=exam.id,
        exam_date=date(2026, 5, 1),
        title="مرحله ۱",
    )

    submit_student_exam_result(
        db_session,
        student=st12,
        exam_session_id=session.id,
        group_data=[{"reporting_group_id": rg.id, "group_title": rg.title, "percentage": 76.5}],
        overall_rank=120,
    )

    st_analytics = get_student_exam_analytics(db_session, st12.id)
    assert st_analytics["has_data"] is True
    assert st_analytics["overall_trends"][0]["average_percentage"] == 76.5
    assert "زیست و شیمی" in st_analytics["subject_trends"]
    assert st_analytics["subject_stats"]["زیست و شیمی"]["average"] == 76.5
    assert st_analytics["history"][0]["subjects"][0]["is_group"] is True

    tutor_st_analytics = get_tutor_student_analytics(db_session, st12.id)
    assert tutor_st_analytics["analytics"]["overall_trends"][0]["average_percentage"] == 76.5

    sess_analytics = get_tutor_session_analytics(db_session, session.id)
    assert sess_analytics["all_subjects"] == ["زیست و شیمی"]
    assert sess_analytics["subject_averages"]["زیست و شیمی"] == 76.5
    assert sess_analytics["students"][0]["average_percentage"] == 76.5
    assert sess_analytics["students"][0]["subject_scores"]["زیست و شیمی"]["percentage"] == 76.5

    # Verify HTML responses render reporting group scores cleanly
    st_token, _ = create_session(db_session, st12)
    client.cookies.set(SESSION_COOKIE_NAME, st_token)
    res_st = client.get("/student/exams/analytics")
    assert res_st.status_code == 200
    assert "زیست و شیمی" in res_st.text
    assert "76.5%" in res_st.text

    tutor_token, _ = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, tutor_token)
    res_tutor = client.get(f"/tutor/exams/sessions/{session.id}")
    assert res_tutor.status_code == 200
    assert "زیست و شیمی" in res_tutor.text
    assert "76.5%" in res_tutor.text


def test_tutor_score_correction_subjects_and_rg_ownership(
    db_session: Session,
    client: TestClient,
    tutor_session,
):
    sub_bio, sub_chem, track_tajrobi = _setup_curriculum(db_session)
    st12 = create_student(
        db_session,
        username="st12_corr",
        full_name="Student Correction",
        password="Password123!",
        grade="12",
    )
    assign_student_track(db_session, st12.id, track_tajrobi.id)

    exam_a = create_exam(db_session, title="Exam A")
    session_a = create_exam_session(
        db_session,
        exam_id=exam_a.id,
        exam_date=date(2026, 5, 2),
        track_subjects_map={track_tajrobi.id: [sub_bio.id, sub_chem.id]},
    )
    result = submit_student_exam_result(
        db_session,
        student=st12,
        exam_session_id=session_a.id,
        subject_data=[
            {"subject_id": sub_bio.id, "correct_answers": 10, "incorrect_answers": 2, "percentage": 50.0},
            {"subject_id": sub_chem.id, "correct_answers": 12, "incorrect_answers": 3, "percentage": 60.0},
        ],
        overall_rank=200,
    )

    tutor_token, tutor_sess = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, tutor_token)

    resp = client.post(
        f"/tutor/exams/results/{result.id}/correct",
        data={
            "csrf_token": tutor_sess.csrf_token,
            f"subject_{sub_bio.id}_correct": "20",
            f"subject_{sub_bio.id}_incorrect": "1",
            f"subject_{sub_bio.id}_percentage": "82.5",
            f"subject_{sub_chem.id}_correct": "15",
            f"subject_{sub_chem.id}_incorrect": "0",
            f"subject_{sub_chem.id}_percentage": "75.0",
            "overall_rank": "85",
            "correction_reason": "Verified against official sheet",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    updated = get_student_exam_result_by_id(db_session, result.id, populate_existing=True)
    assert updated.is_tutor_corrected is True
    assert updated.overall_rank == 85
    by_sub = {sr.subject_id: sr for sr in updated.subject_results}
    assert by_sub[sub_bio.id].correct_answers == 20
    assert by_sub[sub_bio.id].percentage == 82.5
    assert by_sub[sub_chem.id].percentage == 75.0

    audit = db_session.query(ExamAuditLog).filter(ExamAuditLog.entity_id == result.id, ExamAuditLog.action == "CORRECTED").first()
    assert audit is not None
    assert "82.5" in audit.new_value

    # Cross-exam reporting group ID must be rejected
    exam_b = create_exam(db_session, title="Exam B")
    gtc_b = configure_exam_grade_track(
        db_session,
        exam_id=exam_b.id,
        grade="12",
        track_id=track_tajrobi.id,
        groups_map={"گروه غیرمجاز": [sub_bio.id]},
    )
    foreign_rg = gtc_b.reporting_groups[0]

    with pytest.raises(ExamValidationError, match="does not belong"):
        tutor_correct_exam_result(
            db_session,
            result_id=result.id,
            group_data=[{"reporting_group_id": foreign_rg.id, "group_title": "گروه غیرمجاز", "percentage": 90.0}],
        )


def test_grade_plus_track_eligibility_blocks_wrong_grade_unless_assigned(
    db_session: Session,
    client: TestClient,
):
    sub_bio, sub_chem, track_tajrobi = _setup_curriculum(db_session)
    st12 = create_student(db_session, username="elig_12", full_name="Grade 12", password="Password123!", grade="12")
    st10 = create_student(db_session, username="elig_10", full_name="Grade 10", password="Password123!", grade="10")
    assign_student_track(db_session, st12.id, track_tajrobi.id)
    assign_student_track(db_session, st10.id, track_tajrobi.id)

    exam = create_exam(db_session, title="Grade 12 Only Exam")
    gtc = configure_exam_grade_track(
        db_session,
        exam_id=exam.id,
        grade="12",
        track_id=track_tajrobi.id,
        groups_map={"عمومی و اختصاصی": [sub_bio.id, sub_chem.id]},
    )
    rg = gtc.reporting_groups[0]
    session = create_exam_session(
        db_session,
        exam_id=exam.id,
        exam_date=date(2026, 5, 10),
    )

    avail_12 = get_student_available_exams(db_session, st12)
    avail_10 = get_student_available_exams(db_session, st10)
    assert len(avail_12["upcoming"]) + len(avail_12["past"]) == 1
    assert len(avail_10["upcoming"]) + len(avail_10["past"]) == 0

    with pytest.raises(ExamValidationError, match="not available"):
        submit_student_exam_result(
            db_session,
            student=st10,
            exam_session_id=session.id,
            group_data=[{"reporting_group_id": rg.id, "group_title": rg.title, "percentage": 55.0}],
        )

    st10_token, _ = create_session(db_session, st10)
    client.cookies.set(SESSION_COOKIE_NAME, st10_token)
    get_form = client.get(f"/student/exams/{session.id}/submit")
    assert get_form.status_code == 403

    # Direct assignment grants access even if grade differs
    assign_exam_series_to_students(db_session, exam.id, [st10.id], bypass_eligibility=True)
    avail_10_after = get_student_available_exams(db_session, st10)
    assert len(avail_10_after["upcoming"]) + len(avail_10_after["past"]) == 1


def test_deadlines_timezone_duplicate_date_and_route_errors(
    db_session: Session,
    client: TestClient,
    tutor_session,
):
    sub_bio, sub_chem, track_tajrobi = _setup_curriculum(db_session)
    st12 = create_student(db_session, username="st12_dl", full_name="Deadline Student", password="Password123!", grade="12")
    assign_student_track(db_session, st12.id, track_tajrobi.id)

    exam = create_exam(db_session, title="Deadline & Error Exam", submission_days_after_exam=2)
    d1 = date(2026, 1, 10)
    d2 = date(2026, 1, 24)
    s1 = create_exam_session(
        db_session,
        exam_id=exam.id,
        exam_date=d1,
        track_subjects_map={track_tajrobi.id: [sub_bio.id]},
    )
    s2 = create_exam_session(
        db_session,
        exam_id=exam.id,
        exam_date=d2,
        track_subjects_map={track_tajrobi.id: [sub_bio.id]},
    )

    expected_dl_utc = datetime.combine(d1 + timedelta(days=2), time(23, 59, 59), tzinfo=get_timezone()).astimezone(timezone.utc)
    s1_dl = s1.submission_deadline
    if s1_dl.tzinfo is None:
        s1_dl = s1_dl.replace(tzinfo=timezone.utc)
    assert s1_dl == expected_dl_utc

    # Naive submission_deadline stored in SQLite must not raise TypeError in overview
    s2.submission_deadline = datetime(2025, 1, 1, 23, 59, 59)
    db_session.commit()
    assign_exam_series_to_students(db_session, exam.id, [st12.id])
    overview = get_bulk_series_submission_overview(db_session, exam_id=exam.id)
    assert overview["total_sessions"] == 2

    # Updating session date to existing date raises ExamValidationError cleanly
    with pytest.raises(ExamValidationError, match="already exists"):
        update_exam_session(db_session, s2.id, exam_date=d1)

    tutor_token, tutor_sess = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, tutor_token)

    r_bad_uuid = client.post(
        f"/tutor/exams/{exam.id}/grade-track",
        data={"csrf_token": tutor_sess.csrf_token, "grade": "12", "track_id": "not-a-uuid"},
    )
    assert r_bad_uuid.status_code == 400

    r_missing_student = client.get(f"/tutor/exams/students/{uuid.uuid4()}")
    assert r_missing_student.status_code == 404

    r_missing_delete = client.post(
        f"/tutor/exams/{uuid.uuid4()}/delete",
        data={"csrf_token": tutor_sess.csrf_token},
    )
    assert r_missing_delete.status_code == 404
