import uuid
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy.orm import Session

from app.core.timezone import now_utc

from app.models.practice_exam import (
    PracticeExam,
    PracticeExamBooklet,
    StudentPracticeAttempt,
    StudentPracticeBookletAttempt,
)
from app.services.academic_service import (
    assign_student_track,
    create_subject,
    create_track,
    set_track_subjects,
)
from app.services.practice_exam_service import (
    PracticeExamLockedError,
    PracticeExamNotFoundError,
    PracticeExamValidationError,
    add_practice_exam_booklet,
    assign_practice_exam_to_students,
    calculate_practice_exam_results,
    configure_practice_exam_questions,
    create_practice_exam,
    create_practice_reporting_group,
    get_practice_exam_by_id,
    get_practice_exam_detailed_results,
    get_student_available_practice_exams,
    get_student_booklet_state,
    start_practice_attempt,
    submit_booklet_answers,
)
from app.services.user_service import create_student


@pytest.fixture
def practice_setup(db_session: Session):
    # Subjects
    sub_geom = create_subject(db_session, name="هندسه", grades=["11", "12"])
    sub_calc = create_subject(db_session, name="حسابان", grades=["11", "12"])
    sub_stat = create_subject(db_session, name="آمار و احتمال", grades=["11", "12"])
    sub_phys = create_subject(db_session, name="فیزیک ریاضی", grades=["11", "12"])

    # Track: Riazi
    track_riazi = create_track(db_session, name="ریاضی فیزیک")
    set_track_subjects(db_session, track_riazi.id, [sub_geom.id, sub_calc.id, sub_stat.id, sub_phys.id])

    # Track: Tajrobi
    sub_bio = create_subject(db_session, name="زیست‌شناسی", grades=["11", "12"])
    track_tajrobi = create_track(db_session, name="علوم تجربی")
    set_track_subjects(db_session, track_tajrobi.id, [sub_bio.id])

    # Eligible Student: Grade 11, Track Riazi
    st_riazi_11 = create_student(
        db_session, username="riazi11", full_name="Riazi Student 11", password="pass", grade="11"
    )
    assign_student_track(db_session, st_riazi_11.id, track_riazi.id)

    # Ineligible Student: Grade 12, Track Riazi
    st_riazi_12 = create_student(
        db_session, username="riazi12", full_name="Riazi Student 12", password="pass", grade="12"
    )
    assign_student_track(db_session, st_riazi_12.id, track_riazi.id)

    # Ineligible Student: Grade 11, Track Tajrobi
    st_tajrobi_11 = create_student(
        db_session, username="taj11", full_name="Tajrobi Student 11", password="pass", grade="11"
    )
    assign_student_track(db_session, st_tajrobi_11.id, track_tajrobi.id)

    return {
        "track_riazi": track_riazi,
        "track_tajrobi": track_tajrobi,
        "sub_geom": sub_geom,
        "sub_calc": sub_calc,
        "sub_stat": sub_stat,
        "sub_phys": sub_phys,
        "st_riazi_11": st_riazi_11,
        "st_riazi_12": st_riazi_12,
        "st_tajrobi_11": st_tajrobi_11,
    }
def test_practice_exam_creation_and_booklets(db_session: Session, practice_setup):
    setup = practice_setup
    exam = create_practice_exam(
        db_session,
        title="آزمون ریاضی جامع یازدهم",
        grade="11",
        academic_track_id=setup["track_riazi"].id,
        description="شامل دو دفترچه عمومی و اختصاصی",
        is_timed=True,
    )
    assert exam.id is not None
    assert exam.is_timed is True
    assert exam.grade == "11"

    # Add Booklet 1: Q1 to Q20, 30 mins
    b1 = add_practice_exam_booklet(
        db_session,
        practice_exam_id=exam.id,
        title="دفترچه اول - ریاضیات پایه",
        pdf_file_path="practice_booklets/mock_b1.pdf",
        pdf_file_name="b1.pdf",
        question_start=1,
        question_end=20,
        duration_minutes=30,
    )
    assert b1.order_index == 1
    assert b1.question_start == 1
    assert b1.question_end == 20

    # Add Booklet 2: Q21 to Q40, 25 mins
    b2 = add_practice_exam_booklet(
        db_session,
        practice_exam_id=exam.id,
        title="دفترچه دوم - فیزیک",
        pdf_file_path="practice_booklets/mock_b2.pdf",
        pdf_file_name="b2.pdf",
        question_start=21,
        question_end=40,
        duration_minutes=25,
    )
    assert b2.order_index == 2
    assert b2.question_start == 21
    assert b2.question_end == 40


def test_question_configuration_and_choice_validation(db_session: Session, practice_setup):
    setup = practice_setup
    exam = create_practice_exam(
        db_session,
        title="آزمون تست سوالات",
        grade="11",
        academic_track_id=setup["track_riazi"].id,
    )
    b1 = add_practice_exam_booklet(
        db_session,
        practice_exam_id=exam.id,
        title="دفترچه ۱",
        pdf_file_path="practice_booklets/test.pdf",
        pdf_file_name="test.pdf",
        question_start=1,
        question_end=5,
    )

    # Valid config: 5 questions with choices in 1..4
    q_defs = [
        {"question_number": 1, "correct_choice": 1, "subject_id": setup["sub_geom"].id},
        {"question_number": 2, "correct_choice": 2, "subject_id": setup["sub_calc"].id},
        {"question_number": 3, "correct_choice": 3, "subject_id": setup["sub_stat"].id},
        {"question_number": 4, "correct_choice": 4, "subject_id": setup["sub_phys"].id},
        {"question_number": 5, "correct_choice": 1, "subject_id": setup["sub_geom"].id},
    ]
    configured = configure_practice_exam_questions(db_session, exam.id, q_defs)
    assert len(configured) == 5

    # Invalid choice (choice 5 is invalid for 4-choice exam)
    invalid_defs = [
        {"question_number": 1, "correct_choice": 5, "subject_id": setup["sub_geom"].id},
    ]
    with pytest.raises(PracticeExamValidationError) as exc:
        configure_practice_exam_questions(db_session, exam.id, invalid_defs)
    assert "must be 1, 2, 3, or 4" in str(exc.value)
def test_flexible_reporting_groups_and_scoring(db_session: Session, practice_setup):
    setup = practice_setup
    exam = create_practice_exam(
        db_session,
        title="آزمون ترکیبی هندسه و حسابان",
        grade="11",
        academic_track_id=setup["track_riazi"].id,
    )
    b1 = add_practice_exam_booklet(
        db_session,
        practice_exam_id=exam.id,
        title="دفترچه ۱",
        pdf_file_path="practice_booklets/t1.pdf",
        pdf_file_name="t1.pdf",
        question_start=1,
        question_end=6,
    )

    # Tutor creates a combined reporting group "ریاضیات"
    group_math = create_practice_reporting_group(db_session, exam.id, "ریاضیات")

    # Q1-Q2: Geometry in group_math
    # Q3-Q4: Calculus in group_math
    # Q5-Q6: Physics WITHOUT group (individual subject score)
    q_defs = [
        {"question_number": 1, "correct_choice": 1, "subject_id": setup["sub_geom"].id, "reporting_group_id": group_math.id},
        {"question_number": 2, "correct_choice": 2, "subject_id": setup["sub_geom"].id, "reporting_group_id": group_math.id},
        {"question_number": 3, "correct_choice": 3, "subject_id": setup["sub_calc"].id, "reporting_group_id": group_math.id},
        {"question_number": 4, "correct_choice": 4, "subject_id": setup["sub_calc"].id, "reporting_group_id": group_math.id},
        {"question_number": 5, "correct_choice": 1, "subject_id": setup["sub_phys"].id, "reporting_group_id": None},
        {"question_number": 6, "correct_choice": 2, "subject_id": setup["sub_phys"].id, "reporting_group_id": None},
    ]
    configure_practice_exam_questions(db_session, exam.id, q_defs)

    # Student takes exam
    student = setup["st_riazi_11"]
    attempt = start_practice_attempt(db_session, student, exam.id)

    # Student answers:
    # Q1: 1 (correct), Q2: 3 (incorrect), Q3: 3 (correct), Q4: None (unanswered) -> Math: 4 questions, 2C, 1I, 1U
    # Math percentage = ((3*2 - 1) / (3*4)) * 100 = (5 / 12) * 100 = 41.67%
    # Q5: 1 (correct), Q6: 2 (correct) -> Physics: 2 questions, 2C, 0I, 0U -> 100%
    answers = {1: 1, 2: 3, 3: 3, 4: None, 5: 1, 6: 2}
    res = submit_booklet_answers(db_session, student, attempt.id, b1.id, answers, advance_to_next=True)
    assert res["completed"] is True

    # Inspect detailed results
    details = get_practice_exam_detailed_results(db_session, attempt.id)
    assert details["total_questions"] == 6
    assert details["total_correct"] == 4
    assert details["total_incorrect"] == 1
    assert details["total_unanswered"] == 1

    # Verify combined group "ریاضیات"
    math_group = next(g for g in details["reporting_groups"] if g["name"] == "ریاضیات")
    assert math_group["total"] == 4
    assert math_group["correct"] == 2
    assert math_group["incorrect"] == 1
    assert math_group["unanswered"] == 1
    assert math_group["percentage"] == 41.67

    # Verify individual physics subject
    phys_sub = next(s for s in details["individual_subjects"] if s["name"] == "فیزیک ریاضی")
    assert phys_sub["total"] == 2
    assert phys_sub["correct"] == 2
    assert phys_sub["percentage"] == 100.0
def test_booklet_progression_and_answer_locking(db_session: Session, practice_setup):
    setup = practice_setup
    exam = create_practice_exam(
        db_session,
        title="آزمون دو مرحله‌ای",
        grade="11",
        academic_track_id=setup["track_riazi"].id,
        is_timed=True,
    )
    b1 = add_practice_exam_booklet(
        db_session,
        practice_exam_id=exam.id,
        title="دفترچه ۱",
        pdf_file_path="practice_booklets/b1.pdf",
        pdf_file_name="b1.pdf",
        question_start=1,
        question_end=2,
        duration_minutes=15,
    )
    b2 = add_practice_exam_booklet(
        db_session,
        practice_exam_id=exam.id,
        title="دفترچه ۲",
        pdf_file_path="practice_booklets/b2.pdf",
        pdf_file_name="b2.pdf",
        question_start=3,
        question_end=4,
        duration_minutes=15,
    )
    q_defs = [
        {"question_number": 1, "correct_choice": 1, "subject_id": setup["sub_calc"].id},
        {"question_number": 2, "correct_choice": 2, "subject_id": setup["sub_calc"].id},
        {"question_number": 3, "correct_choice": 3, "subject_id": setup["sub_phys"].id},
        {"question_number": 4, "correct_choice": 4, "subject_id": setup["sub_phys"].id},
    ]
    configure_practice_exam_questions(db_session, exam.id, q_defs)

    student = setup["st_riazi_11"]
    attempt = start_practice_attempt(db_session, student, exam.id)

    # 1. Save answers in Booklet 1 (does not advance or lock)
    submit_booklet_answers(db_session, student, attempt.id, b1.id, {1: 1, 2: 2}, advance_to_next=False)
    state_b1 = get_student_booklet_state(db_session, attempt.id, b1.id)
    assert state_b1["is_locked"] is False

    # 2. Advance to Booklet 2
    adv_res = submit_booklet_answers(db_session, student, attempt.id, b1.id, {1: 1, 2: 2}, advance_to_next=True)
    assert adv_res["advanced"] is True
    assert adv_res["completed"] is False
    assert adv_res["next_booklet_id"] == str(b2.id)

    # 3. Verify Booklet 1 is now locked
    state_b1_after = get_student_booklet_state(db_session, attempt.id, b1.id)
    assert state_b1_after["is_locked"] is True

    # 4. Attempting to submit or modify answers on locked Booklet 1 MUST be rejected by server
    with pytest.raises(PracticeExamLockedError) as exc:
        submit_booklet_answers(db_session, student, attempt.id, b1.id, {1: 4, 2: 4}, advance_to_next=False)
    assert "locked" in str(exc.value)

    # 5. Booklet 2 is active and unlocked
    state_b2 = get_student_booklet_state(db_session, attempt.id, b2.id)
    assert state_b2["is_locked"] is False

    # 6. Complete Booklet 2
    fin_res = submit_booklet_answers(db_session, student, attempt.id, b2.id, {3: 3, 4: 4}, advance_to_next=True)
    assert fin_res["completed"] is True

    # Check attempt completion status and 100% score
    db_session.refresh(attempt)
    assert attempt.status == "COMPLETED"
    assert attempt.overall_percentage == 100.0


def test_server_timer_expiration_enforcement(db_session: Session, practice_setup):
    setup = practice_setup
    exam = create_practice_exam(
        db_session,
        title="آزمون انقضای زمان",
        grade="11",
        academic_track_id=setup["track_riazi"].id,
        is_timed=True,
    )
    b1 = add_practice_exam_booklet(
        db_session,
        practice_exam_id=exam.id,
        title="دفترچه با زمان کوتاه",
        pdf_file_path="practice_booklets/exp.pdf",
        pdf_file_name="exp.pdf",
        question_start=1,
        question_end=2,
        duration_minutes=5,
    )
    configure_practice_exam_questions(db_session, exam.id, [
        {"question_number": 1, "correct_choice": 1, "subject_id": setup["sub_calc"].id},
        {"question_number": 2, "correct_choice": 2, "subject_id": setup["sub_calc"].id},
    ])

    student = setup["st_riazi_11"]
    attempt = start_practice_attempt(db_session, student, exam.id)

    # Artificially expire the timer on the server
    b_attempt = attempt.booklet_attempts[0]
    b_attempt.expires_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    db_session.commit()

    # get_student_booklet_state must detect timer expiration and lock the booklet
    state = get_student_booklet_state(db_session, attempt.id, b1.id)
    assert state["is_locked"] is True
    assert state["remaining_seconds"] == 0

    # Submitting answers to expired booklet must fail
    with pytest.raises(PracticeExamLockedError):
        submit_booklet_answers(db_session, student, attempt.id, b1.id, {1: 1, 2: 2}, advance_to_next=False)
def test_grade_and_track_restrictions_and_direct_assignment(db_session: Session, practice_setup):
    setup = practice_setup
    exam = create_practice_exam(
        db_session,
        title="آزمون اختصاصی یازدهم ریاضی",
        grade="11",
        academic_track_id=setup["track_riazi"].id,
    )
    b1 = add_practice_exam_booklet(
        db_session,
        practice_exam_id=exam.id,
        title="دفترچه ۱",
        pdf_file_path="practice_booklets/r.pdf",
        pdf_file_name="r.pdf",
        question_start=1,
        question_end=2,
    )

    # 1. Eligible student (Grade 11 Riazi) sees it
    eligible_st = setup["st_riazi_11"]
    avail = get_student_available_practice_exams(db_session, eligible_st)
    assert any(e.id == exam.id for e in avail)

    # 2. Ineligible student (Grade 12 Riazi) does NOT see it
    ineligible_grade = setup["st_riazi_12"]
    avail_g12 = get_student_available_practice_exams(db_session, ineligible_grade)
    assert not any(e.id == exam.id for e in avail_g12)

    # 3. Ineligible student (Grade 11 Tajrobi) cannot start it
    ineligible_track = setup["st_tajrobi_11"]
    with pytest.raises(PracticeExamValidationError) as exc:
        start_practice_attempt(db_session, ineligible_track, exam.id)
    assert "not eligible" in str(exc.value)

    # 4. Direct assignment overrides restriction
    assign_practice_exam_to_students(db_session, exam.id, [ineligible_track.id])
    avail_after_assign = get_student_available_practice_exams(db_session, ineligible_track)
    assert any(e.id == exam.id for e in avail_after_assign)

    # Now the assigned student can start and take the exam
    att = start_practice_attempt(db_session, ineligible_track, exam.id)
    assert att.id is not None


def test_student_can_retake_completed_practice_exam(
    db_session: Session,
    practice_setup: dict,
):
    setup = practice_setup
    student = setup["st_riazi_11"]

    exam = create_practice_exam(
        db_session,
        title="Retake Test Exam",
        grade="11",
        academic_track_id=setup["track_riazi"].id,
        is_timed=False,
    )
    add_practice_exam_booklet(
        db_session,
        practice_exam_id=exam.id,
        title="Booklet 1",
        pdf_file_path="mock.pdf",
        pdf_file_name="mock.pdf",
        question_start=1,
        question_end=5,
    )

    # 1. Start attempt 1
    att1 = start_practice_attempt(db_session, student, exam.id)
    assert att1.status == "IN_PROGRESS"

    # Complete attempt 1
    att1.status = "COMPLETED"
    att1.completed_at = now_utc()
    att1.overall_percentage = 85.0
    db_session.commit()

    # 2. Student starts exam again -> gets a new distinct in-progress attempt
    att2 = start_practice_attempt(db_session, student, exam.id)
    assert att2.id != att1.id
    assert att2.status == "IN_PROGRESS"

    # 3. Available exams list has latest_attempt pointing to the new attempt
    avail = get_student_available_practice_exams(db_session, student)
    user_exam = next(e for e in avail if e.id == exam.id)
    assert user_exam.latest_attempt.id == att2.id
    assert user_exam.latest_attempt.status == "IN_PROGRESS"
