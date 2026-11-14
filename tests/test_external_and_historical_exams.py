import uuid
from datetime import date, timedelta
import pytest
from sqlalchemy.orm import Session

from app.models.exam import HistoricalExamResult, StudentExamResult
from app.services.academic_service import (
    assign_student_track,
    create_subject,
    create_track,
    set_track_subjects,
)
from app.services.exam_service import (
    assign_external_exam_to_students,
    create_exam,
    create_exam_session,
    create_historical_exam_result,
    get_historical_exam_result_by_id,
    get_student_available_exams,
    get_student_exam_result_by_id,
    get_student_external_exams_in_date_range,
    list_historical_exam_results,
    submit_student_exam_result,
)
from app.services.user_service import create_student


@pytest.fixture
def ext_hist_setup(db_session: Session):
    sub_bio = create_subject(db_session, name="زیست‌شناسی", grades=["12"])
    sub_chem = create_subject(db_session, name="شیمی", grades=["12"])

    track = create_track(db_session, name="تجربی ۱۲")
    set_track_subjects(db_session, track.id, [sub_bio.id, sub_chem.id])

    student1 = create_student(
        db_session, username="ext_st1", full_name="Student One", password="pass", grade="12"
    )
    assign_student_track(db_session, student1.id, track.id)

    student2 = create_student(
        db_session, username="ext_st2", full_name="Student Two", password="pass", grade="12"
    )
    assign_student_track(db_session, student2.id, track.id)

    return {
        "sub_bio": sub_bio,
        "sub_chem": sub_chem,
        "track": track,
        "student1": student1,
        "student2": student2,
    }
def test_external_exam_report_card_persistence(db_session: Session, ext_hist_setup):
    setup = ext_hist_setup
    st1 = setup["student1"]

    exam = create_exam(db_session, title="آزمون قلم‌چی - سنجش پیشرفت ۱")
    session = create_exam_session(
        db_session,
        exam_id=exam.id,
        exam_date=date.today(),
        track_subjects_map={
            setup["track"].id: [setup["sub_bio"].id, setup["sub_chem"].id],
        },
    )

    # Student submits result with report card path and name
    result = submit_student_exam_result(
        db=db_session,
        student=st1,
        exam_session_id=session.id,
        subject_data=[
            {"subject_id": setup["sub_bio"].id, "correct_answers": 25, "incorrect_answers": 5, "percentage": 75.0},
            {"subject_id": setup["sub_chem"].id, "correct_answers": 20, "incorrect_answers": 4, "percentage": 62.5},
        ],
        overall_rank=340,
        notes="کارنامه رسمی پیوست گردید",
        report_card_file_path="report_cards/karnameh_123.pdf",
        report_card_file_name="karnameh_official.pdf",
    )

    assert result.id is not None
    assert result.report_card_file_path == "report_cards/karnameh_123.pdf"
    assert result.report_card_file_name == "karnameh_official.pdf"
    assert result.overall_rank == 340

    # Retrieve and verify persistence
    loaded = get_student_exam_result_by_id(db_session, result.id)
    assert loaded is not None
    assert loaded.report_card_file_path == "report_cards/karnameh_123.pdf"
    assert loaded.report_card_file_name == "karnameh_official.pdf"
def test_historical_exam_creation_and_separation(db_session: Session, ext_hist_setup):
    setup = ext_hist_setup
    st1 = setup["student1"]
    st2 = setup["student2"]

    # Record historical exam for student 1
    past_date = date(2025, 10, 15)
    hist = create_historical_exam_result(
        db=db_session,
        student_id=st1.id,
        exam_name="گزینه دو - مرحله آزمایشی اول",
        exam_date=past_date,
        grade="11",
        academic_track_id=setup["track"].id,
        overall_rank=890,
        notes="ورود آزمایشی سال گذشته",
        subject_scores=[
            {"subject_name": "زیست‌شناسی", "percentage": 78.0},
            {"subject_name": "شیمی", "percentage": 65.5},
        ],
        report_card_file_path="report_cards/hist_st1.pdf",
        report_card_file_name="karnameh_gozineh2.pdf",
    )

    assert hist.id is not None
    assert hist.student_id == st1.id
    assert hist.exam_name == "گزینه دو - مرحله آزمایشی اول"
    assert hist.grade == "11"
    assert len(hist.subject_results) == 2

    # Query for student 1
    st1_histories = list_historical_exam_results(db_session, student_id=st1.id)
    assert len(st1_histories) == 1
    assert st1_histories[0].id == hist.id

    # Query for student 2 (should be empty)
    st2_histories = list_historical_exam_results(db_session, student_id=st2.id)
    assert len(st2_histories) == 0

    # SEPARATION CHECK:
    # Historical exams must NOT appear in scheduled active external exams
    available_active_data = get_student_available_exams(db_session, st1)
    all_sessions = [item["session"] for item in available_active_data["upcoming"] + available_active_data["past"]]
    assert not any(sess.exam.title == hist.exam_name for sess in all_sessions)


def test_study_plan_external_exam_integration(db_session: Session, ext_hist_setup):
    setup = ext_hist_setup
    st1 = setup["student1"]
    st2 = setup["student2"]

    today = date.today()
    in_range_date = today + timedelta(days=5)
    out_of_range_date = today + timedelta(days=30)

    exam1 = create_exam(db_session, title="آزمون سنجش پیش‌نوبت اول")
    sess1 = create_exam_session(
        db_session,
        exam_id=exam1.id,
        exam_date=in_range_date,
        track_subjects_map={
            setup["track"].id: [setup["sub_bio"].id],
        },
    )

    exam2 = create_exam(db_session, title="آزمون دور از بازه")
    sess2 = create_exam_session(
        db_session,
        exam_id=exam2.id,
        exam_date=out_of_range_date,
        track_subjects_map={
            setup["track"].id: [setup["sub_bio"].id],
        },
    )

    # 1. Automatic track-based matching
    plan_exams = get_student_external_exams_in_date_range(
        db=db_session,
        student=st1,
        start_date=today,
        end_date=today + timedelta(days=13),
    )
    assert in_range_date in plan_exams
    assert plan_exams[in_range_date][0].id == sess1.id
    assert plan_exams[in_range_date][0].exam.title == "آزمون سنجش پیش‌نوبت اول"
    assert out_of_range_date not in plan_exams

    # 2. Direct assignment check
    assign_external_exam_to_students(db_session, sess1.id, [st2.id])
    plan_exams_st2 = get_student_external_exams_in_date_range(
        db=db_session,
        student=st2,
        start_date=today,
        end_date=today + timedelta(days=13),
    )
    assert in_range_date in plan_exams_st2
    assert any(e.id == sess1.id for e in plan_exams_st2[in_range_date])
