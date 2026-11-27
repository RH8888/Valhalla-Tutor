import uuid
from datetime import date, datetime, time, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette.datastructures import FormData
from starlette.requests import Request

from app.core.timezone import get_timezone
from app.models.exam import ExamAuditLog, ExternalExamAssignment
from app.routers.student_exams import get_student_analytics_page, get_submit_result_form
from app.routers.tutor_exams import (
    get_session_detail,
    get_tutor_student_analytics_page,
    post_configure_grade_track,
    post_correct_result,
    post_delete_series,
)
from app.services.academic_service import (
    assign_student_track,
    create_subject,
    create_track,
    set_track_subjects,
)
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


def _dummy_request(path: str = "/") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": [],
        "scheme": "http",
        "server": ("testserver", 80),
    }
    return Request(scope)


def _setup_curriculum(db: Session):
    sub_bio = create_subject(db, name="زیست‌شناسی", grades=["10", "11", "12"])
    sub_chem = create_subject(db, name="شیمی", grades=["10", "11", "12"])
    track_tajrobi = create_track(db, name="تجربی")
    set_track_subjects(db, track_tajrobi.id, [sub_bio.id, sub_chem.id])
    return sub_bio, sub_chem, track_tajrobi


def test_reporting_group_analytics_and_session_table(
    db_session: Session,
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
        reporting_groups_data=[{"title": "زیست و شیمی", "subject_ids": [sub_bio.id, sub_chem.id]}],
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

    # Verify HTML responses from routers render reporting group scores cleanly
    _, tutor_sess = tutor_session
    res_st = get_student_analytics_page(
        request=_dummy_request("/student/exams/analytics"),
        db=db_session,
        current_user=st12,
        current_session=tutor_sess,
    )
    assert res_st.status_code == 200
    st_body = res_st.body.decode("utf-8")
    assert "زیست و شیمی" in st_body
    assert "76.5%" in st_body

    res_tutor = get_session_detail(
        request=_dummy_request(f"/tutor/exams/sessions/{session.id}"),
        session_id=session.id,
        db=db_session,
        current_user=tutor_user,
        current_session=tutor_sess,
    )
    assert res_tutor.status_code == 200
    tutor_body = res_tutor.body.decode("utf-8")
    assert "زیست و شیمی" in tutor_body
    assert "76.5%" in tutor_body


def test_tutor_score_correction_subjects_and_rg_ownership(
    db_session: Session,
    tutor_user,
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

    form = FormData(
        [
            (f"subject_{sub_bio.id}_correct", "20"),
            (f"subject_{sub_bio.id}_incorrect", "1"),
            (f"subject_{sub_bio.id}_percentage", "82.5"),
            (f"subject_{sub_chem.id}_correct", "15"),
            (f"subject_{sub_chem.id}_incorrect", "0"),
            (f"subject_{sub_chem.id}_percentage", "75.0"),
            ("overall_rank", "85"),
            ("correction_reason", "Verified against official sheet"),
        ]
    )
    resp = post_correct_result(
        request=_dummy_request(f"/tutor/exams/results/{result.id}/correct"),
        result_id=result.id,
        form_data=form,
        db=db_session,
        current_user=tutor_user,
    )
    assert resp.status_code == 303

    updated = get_student_exam_result_by_id(db_session, result.id, populate_existing=True)
    assert updated.is_tutor_corrected is True
    assert updated.overall_rank == 85
    by_sub = {sr.subject_id: sr for sr in updated.subject_results}
    assert by_sub[sub_bio.id].correct_answers == 20
    assert by_sub[sub_bio.id].percentage == 82.5
    assert by_sub[sub_chem.id].percentage == 75.0

    audit = (
        db_session.query(ExamAuditLog)
        .filter(ExamAuditLog.entity_id == result.id, ExamAuditLog.action == "CORRECTED")
        .first()
    )
    assert audit is not None
    assert "82.5" in audit.new_value

    # Cross-exam reporting group ID must be rejected
    exam_b = create_exam(db_session, title="Exam B")
    gtc_b = configure_exam_grade_track(
        db_session,
        exam_id=exam_b.id,
        grade="12",
        track_id=track_tajrobi.id,
        reporting_groups_data=[{"title": "گروه غیرمجاز", "subject_ids": [sub_bio.id]}],
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
    tutor_session,
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
        reporting_groups_data=[{"title": "عمومی و اختصاصی", "subject_ids": [sub_bio.id, sub_chem.id]}],
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

    _, sess = tutor_session
    with pytest.raises(HTTPException) as exc_info:
        get_submit_result_form(
            request=_dummy_request(f"/student/exams/{session.id}/submit"),
            session_id=session.id,
            db=db_session,
            current_user=st10,
            current_session=sess,
        )
    assert exc_info.value.status_code == 403

    # Direct assignment grants access even if grade differs
    db_session.add(ExternalExamAssignment(exam_session_id=session.id, student_id=st10.id))
    db_session.commit()
    avail_10_after = get_student_available_exams(db_session, st10)
    assert len(avail_10_after["upcoming"]) + len(avail_10_after["past"]) == 1


def test_deadlines_timezone_duplicate_date_and_route_errors(
    db_session: Session,
    tutor_user,
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

    expected_dl_utc = datetime.combine(
        d1 + timedelta(days=2),
        time(23, 59, 59),
        tzinfo=get_timezone(),
    ).astimezone(timezone.utc)
    s1_dl = s1.submission_deadline
    if s1_dl.tzinfo is None:
        s1_dl = s1_dl.replace(tzinfo=timezone.utc)
    assert s1_dl == expected_dl_utc

    # Naive submission_deadline stored in SQLite must not raise TypeError in overview
    s2.submission_deadline = datetime(2025, 1, 1, 23, 59, 59)
    db_session.commit()
    configure_exam_grade_track(
        db_session,
        exam_id=exam.id,
        grade="12",
        track_id=track_tajrobi.id,
        reporting_groups_data=[{"title": "زیست", "subject_ids": [sub_bio.id]}],
    )
    assign_exam_series_to_students(db_session, exam.id, [st12.id])
    overview = get_bulk_series_submission_overview(db_session, exam_id=exam.id)
    assert len(overview["sessions"]) == 2

    # Updating session date to existing date raises ExamValidationError cleanly
    with pytest.raises(ExamValidationError, match="already exists"):
        update_exam_session(db_session, s2.id, exam_date=d1)

    _, tutor_sess = tutor_session
    with pytest.raises(HTTPException) as bad_uuid_exc:
        post_configure_grade_track(
            request=_dummy_request(f"/tutor/exams/{exam.id}/grade-track"),
            exam_id=exam.id,
            form_data=FormData([("grade", "12"), ("track_id", "not-a-uuid")]),
            db=db_session,
            current_user=tutor_user,
            current_session=tutor_sess,
        )
    assert bad_uuid_exc.value.status_code == 400

    with pytest.raises(HTTPException) as missing_student_exc:
        get_tutor_student_analytics_page(
            request=_dummy_request("/tutor/exams/students/missing"),
            student_id=uuid.uuid4(),
            db=db_session,
            current_user=tutor_user,
            current_session=tutor_sess,
        )
    assert missing_student_exc.value.status_code == 404

    with pytest.raises(HTTPException) as missing_delete_exc:
        post_delete_series(
            exam_id=uuid.uuid4(),
            db=db_session,
            current_user=tutor_user,
        )
    assert missing_delete_exc.value.status_code == 404
