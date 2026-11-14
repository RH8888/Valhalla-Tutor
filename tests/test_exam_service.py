import uuid
from datetime import date, timedelta
import pytest
from sqlalchemy.orm import Session

from app.models.exam import Exam, ExamSession, StudentExamResult
from app.models.track import AcademicTrack
from app.models.user import User
from app.services.academic_service import (
    assign_student_track,
    create_subject,
    create_track,
    set_track_subjects,
)
from app.services.exam_service import (
    DuplicateExamResultError,
    ExamNotFoundError,
    ExamValidationError,
    archive_exam,
    create_exam,
    create_exam_session,
    get_exam_by_id,
    get_exam_session_by_id,
    get_student_available_exams,
    get_student_exam_analytics,
    get_tutor_session_analytics,
    list_exams,
    submit_student_exam_result,
    update_exam,
    update_student_exam_result,
)
from app.services.user_service import create_student


@pytest.fixture
def exam_test_setup(db_session: Session):
    # Subjects
    sub_bio = create_subject(db_session, name="زیست‌شناسی", grades=["10", "11", "12"])
    sub_chem = create_subject(db_session, name="شیمی", grades=["10", "11", "12"])
    sub_phys = create_subject(db_session, name="فیزیک", grades=["10", "11", "12"])
    sub_math = create_subject(db_session, name="ریاضی تجربی", grades=["10", "11", "12"])
    sub_calc = create_subject(db_session, name="حسابان", grades=["10", "11", "12"])
    sub_geom = create_subject(db_session, name="هندسه", grades=["10", "11", "12"])
    sub_custom = create_subject(db_session, name="هنر و ادبیات", grades=["10", "11", "12"])

    # Tracks
    track_tajrobi = create_track(db_session, name="تجربی")
    set_track_subjects(db_session, track_tajrobi.id, [sub_bio.id, sub_chem.id, sub_phys.id, sub_math.id])

    track_riazi = create_track(db_session, name="ریاضی")
    set_track_subjects(db_session, track_riazi.id, [sub_calc.id, sub_geom.id, sub_phys.id, sub_chem.id])

    track_honar = create_track(db_session, name="هنر اختصاصی")
    set_track_subjects(db_session, track_honar.id, [sub_custom.id])

    # Students
    st_tajrobi = create_student(db_session, username="student_tajrobi", full_name="Student Tajrobi", password="pass")
    assign_student_track(db_session, st_tajrobi.id, track_tajrobi.id)

    st_riazi = create_student(db_session, username="student_riazi", full_name="Student Riazi", password="pass")
    assign_student_track(db_session, st_riazi.id, track_riazi.id)

    st_honar = create_student(db_session, username="student_honar", full_name="Student Honar", password="pass")
    assign_student_track(db_session, st_honar.id, track_honar.id)

    return {
        "sub_bio": sub_bio,
        "sub_chem": sub_chem,
        "sub_phys": sub_phys,
        "sub_math": sub_math,
        "sub_calc": sub_calc,
        "sub_geom": sub_geom,
        "sub_custom": sub_custom,
        "track_tajrobi": track_tajrobi,
        "track_riazi": track_riazi,
        "track_honar": track_honar,
        "st_tajrobi": st_tajrobi,
        "st_riazi": st_riazi,
        "st_honar": st_honar,
    }


def test_exam_crud_and_archival(db_session: Session):
    exam = create_exam(db_session, title="آزمون جامع شماره ۱", description="نوبت اول")
    assert exam.id is not None
    assert exam.title == "آزمون جامع شماره ۱"
    assert exam.is_active is True

    # Empty title rejected
    with pytest.raises(ExamValidationError):
        create_exam(db_session, title="   ")

    # Update
    updated = update_exam(db_session, exam.id, title="آزمون جامع ۱ ویرایش شده", description="توضیح جدید")
    assert updated.title == "آزمون جامع ۱ ویرایش شده"

    # Archive
    archived = archive_exam(db_session, exam.id)
    assert archived.is_active is False

    # List
    active_only = list_exams(db_session, include_inactive=False)
    assert exam.id not in [e.id for e in active_only]
    all_exams = list_exams(db_session, include_inactive=True)
    assert exam.id in [e.id for e in all_exams]


def test_exam_session_different_subject_configurations_per_track(db_session: Session, exam_test_setup):
    s = exam_test_setup
    exam = create_exam(db_session, title="آزمون سنجش آزمایشی")

    # Track tajrobi subjects: bio, chem, phys, math
    # Track riazi subjects: calc, geom, phys, chem
    track_subjects_map = {
        s["track_tajrobi"].id: [s["sub_bio"].id, s["sub_chem"].id, s["sub_phys"].id, s["sub_math"].id],
        s["track_riazi"].id: [s["sub_calc"].id, s["sub_geom"].id, s["sub_phys"].id, s["sub_chem"].id],
    }
    session = create_exam_session(
        db_session,
        exam_id=exam.id,
        exam_date=date(2026, 12, 1),
        title="مرحله اول سنجش",
        track_subjects_map=track_subjects_map,
    )
    assert session.id is not None
    assert len(session.track_configs) == 2

    # Verify subjects configured for tajrobi
    tc_tajrobi = next(tc for tc in session.track_configs if tc.track_id == s["track_tajrobi"].id)
    tajrobi_subs = {sc.subject.name for sc in tc_tajrobi.subject_configs}
    assert tajrobi_subs == {"زیست‌شناسی", "شیمی", "فیزیک", "ریاضی تجربی"}

    # Verify subjects configured for riazi
    tc_riazi = next(tc for tc in session.track_configs if tc.track_id == s["track_riazi"].id)
    riazi_subs = {sc.subject.name for sc in tc_riazi.subject_configs}
    assert riazi_subs == {"حسابان", "هندسه", "فیزیک", "شیمی"}


def test_exam_session_rejects_subject_not_in_track(db_session: Session, exam_test_setup):
    s = exam_test_setup
    exam = create_exam(db_session, title="آزمون ۲")

    # Try to assign biology to riazi track
    track_subjects_map = {
        s["track_riazi"].id: [s["sub_bio"].id],
    }
    with pytest.raises(ExamValidationError) as exc_info:
        create_exam_session(
            db_session,
            exam_id=exam.id,
            exam_date=date(2026, 12, 5),
            track_subjects_map=track_subjects_map,
        )
    assert "not valid for academic track 'ریاضی'" in str(exc_info.value)


def test_custom_track_support(db_session: Session, exam_test_setup):
    s = exam_test_setup
    exam = create_exam(db_session, title="آزمون هنر و ادبیات")

    track_subjects_map = {
        s["track_honar"].id: [s["sub_custom"].id],
    }
    session = create_exam_session(
        db_session,
        exam_id=exam.id,
        exam_date=date(2026, 12, 10),
        track_subjects_map=track_subjects_map,
    )
    assert len(session.track_configs) == 1
    assert session.track_configs[0].track.name == "هنر اختصاصی"

    # Only student_honar should see this exam
    honar_exams = get_student_available_exams(db_session, s["st_honar"])
    assert len(honar_exams["upcoming"]) == 1

    riazi_exams = get_student_available_exams(db_session, s["st_riazi"])
    assert len(riazi_exams["upcoming"]) == 0


def test_student_result_submission_and_exact_percentage(db_session: Session, exam_test_setup):
    s = exam_test_setup
    exam = create_exam(db_session, title="آزمون جامع ۱")

    session = create_exam_session(
        db_session,
        exam_id=exam.id,
        exam_date=date.today() - timedelta(days=2),
        track_subjects_map={
            s["track_tajrobi"].id: [s["sub_bio"].id, s["sub_chem"].id],
        },
    )

    # Valid submission
    subject_data = [
        {"subject_id": s["sub_bio"].id, "correct_answers": 35, "incorrect_answers": 10, "percentage": 72.5},
        {"subject_id": s["sub_chem"].id, "correct_answers": 20, "incorrect_answers": 5, "percentage": 65.0},
    ]
    res = submit_student_exam_result(
        db_session,
        student=s["st_tajrobi"],
        exam_session_id=session.id,
        subject_data=subject_data,
        overall_rank=125,
        notes="خوب بود",
    )

    assert res.id is not None
    assert res.overall_rank == 125
    assert len(res.subject_results) == 2

    bio_res = next(sr for sr in res.subject_results if sr.subject_id == s["sub_bio"].id)
    assert bio_res.correct_answers == 35
    assert bio_res.incorrect_answers == 10
    # Verify percentage was preserved exactly and NOT recalculated
    assert bio_res.percentage == 72.5

    # Duplicate submission rejected
    with pytest.raises(DuplicateExamResultError):
        submit_student_exam_result(
            db_session,
            student=s["st_tajrobi"],
            exam_session_id=session.id,
            subject_data=subject_data,
        )

    # Edit submitted result
    updated_data = [
        {"subject_id": s["sub_bio"].id, "correct_answers": 36, "incorrect_answers": 9, "percentage": 75.0},
        {"subject_id": s["sub_chem"].id, "correct_answers": 20, "incorrect_answers": 5, "percentage": 65.0},
    ]
    updated_res = update_student_exam_result(
        db_session,
        student=s["st_tajrobi"],
        result_id=res.id,
        subject_data=updated_data,
        overall_rank=110,
    )
    assert updated_res.overall_rank == 110
    bio_updated = next(sr for sr in updated_res.subject_results if sr.subject_id == s["sub_bio"].id)
    assert bio_updated.percentage == 75.0


def test_submission_validation_errors(db_session: Session, exam_test_setup):
    s = exam_test_setup
    exam = create_exam(db_session, title="آزمون ۳")
    session = create_exam_session(
        db_session,
        exam_id=exam.id,
        exam_date=date.today(),
        track_subjects_map={
            s["track_tajrobi"].id: [s["sub_bio"].id],
        },
    )

    # 1. Negative correct answers
    with pytest.raises(ExamValidationError) as exc:
        submit_student_exam_result(
            db_session,
            student=s["st_tajrobi"],
            exam_session_id=session.id,
            subject_data=[{"subject_id": s["sub_bio"].id, "correct_answers": -1, "incorrect_answers": 0, "percentage": 50}],
        )
    assert "non-negative" in str(exc.value)

    # 2. Percentage > 100
    with pytest.raises(ExamValidationError) as exc:
        submit_student_exam_result(
            db_session,
            student=s["st_tajrobi"],
            exam_session_id=session.id,
            subject_data=[{"subject_id": s["sub_bio"].id, "correct_answers": 10, "incorrect_answers": 0, "percentage": 105.0}],
        )
    assert "between 0 and 100" in str(exc.value)

    # 3. Submitting subject not in exam
    with pytest.raises(ExamValidationError) as exc:
        submit_student_exam_result(
            db_session,
            student=s["st_tajrobi"],
            exam_session_id=session.id,
            subject_data=[{"subject_id": s["sub_calc"].id, "correct_answers": 10, "incorrect_answers": 2, "percentage": 70}],
        )
    assert "not allowed" in str(exc.value)

    # 4. Student from different track attempting to submit
    with pytest.raises(ExamValidationError) as exc:
        submit_student_exam_result(
            db_session,
            student=s["st_riazi"],
            exam_session_id=session.id,
            subject_data=[{"subject_id": s["sub_bio"].id, "correct_answers": 10, "incorrect_answers": 2, "percentage": 70}],
        )
    assert "not available for your academic track" in str(exc.value)


def test_analytics_and_improving_declining(db_session: Session, exam_test_setup):
    s = exam_test_setup
    exam = create_exam(db_session, title="آزمون آزمایشی")

    # Exam 1 (past)
    sess1 = create_exam_session(
        db_session,
        exam_id=exam.id,
        exam_date=date(2026, 11, 1),
        title="مرحله ۱",
        track_subjects_map={s["track_tajrobi"].id: [s["sub_bio"].id, s["sub_chem"].id]},
    )
    submit_student_exam_result(
        db_session,
        student=s["st_tajrobi"],
        exam_session_id=sess1.id,
        subject_data=[
            {"subject_id": s["sub_bio"].id, "correct_answers": 20, "incorrect_answers": 10, "percentage": 50.0},
            {"subject_id": s["sub_chem"].id, "correct_answers": 25, "incorrect_answers": 5, "percentage": 80.0},
        ],
    )

    # Exam 2 (recent)
    sess2 = create_exam_session(
        db_session,
        exam_id=exam.id,
        exam_date=date(2026, 11, 10),
        title="مرحله ۲",
        track_subjects_map={s["track_tajrobi"].id: [s["sub_bio"].id, s["sub_chem"].id]},
    )
    submit_student_exam_result(
        db_session,
        student=s["st_tajrobi"],
        exam_session_id=sess2.id,
        subject_data=[
            {"subject_id": s["sub_bio"].id, "correct_answers": 30, "incorrect_answers": 5, "percentage": 75.0},
            {"subject_id": s["sub_chem"].id, "correct_answers": 20, "incorrect_answers": 10, "percentage": 60.0},
        ],
    )

    # Student Analytics
    analytics = get_student_exam_analytics(db_session, s["st_tajrobi"].id)
    assert analytics["has_data"] is True
    assert analytics["results_count"] == 2

    # Bio improved from 50 to 75 (+25)
    improving_names = [item["name"] for item in analytics["improving_declining"]["improving"]]
    assert "زیست‌شناسی" in improving_names

    # Chem declined from 80 to 60 (-20)
    declining_names = [item["name"] for item in analytics["improving_declining"]["declining"]]
    assert "شیمی" in declining_names

    # Tutor Session Analytics
    tutor_sess_analytics = get_tutor_session_analytics(db_session, sess2.id)
    assert tutor_sess_analytics["participant_count"] == 1
    assert tutor_sess_analytics["subject_averages"]["زیست‌شناسی"] == 75.0
    assert tutor_sess_analytics["subject_averages"]["شیمی"] == 60.0
