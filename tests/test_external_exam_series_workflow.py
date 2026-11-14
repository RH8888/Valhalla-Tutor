import os
import uuid
from datetime import date, timedelta
from io import BytesIO
import pytest
from sqlalchemy.orm import Session

from app.models.subject import Subject
from app.models.track import AcademicTrack
from app.models.exam import (
    Exam,
    ExamGradeTrackConfig,
    ExamReportingGroup,
    ExamSeriesAssignment,
    ExamSession,
    ExamSessionAudit,
    StudentExamGroupResult,
    StudentExamResult,
    HistoricalExamResult,
)
from app.models.user import User
from app.services.exam_service import (
    ExamValidationError,
    add_manual_replacement_session,
    assign_exam_series_to_students,
    calculate_recurring_dates,
    check_student_series_eligibility,
    configure_exam_grade_track,
    create_exam,
    create_exam_session,
    create_historical_exam_result,
    dismiss_series_incompatible_assignment,
    evaluate_students_eligibility,
    generate_series_sessions,
    get_all_series_incompatible_students,
    get_exam_by_id,
    get_student_available_exams,
    get_student_external_exams_in_date_range,
    get_student_series_grade_track_config,
    preview_recurring_schedule,
    restore_exam_session,
    skip_exam_session,
    submit_student_exam_result,
    update_future_recurrence,
    update_student_exam_result,
)


@pytest.fixture
def db(db_session: Session) -> Session:
    return db_session


@pytest.fixture
def test_setup(db: Session):
    # Tracks
    track_math = AcademicTrack(name="Mathematics")
    track_exp = AcademicTrack(name="Experimental Science")
    track_hum = AcademicTrack(name="Humanities")
    db.add_all([track_math, track_exp, track_hum])
    db.flush()

    # Subjects
    # Math track subjects
    sub_calc = Subject(name="حسابان")
    sub_geom = Subject(name="هندسه")
    sub_disc = Subject(name="گسسته")
    sub_phys_m = Subject(name="فیزیک ریاضی")
    sub_chem_m = Subject(name="شیمی ریاضی")

    # Exp track subjects
    sub_bio = Subject(name="زیست‌شناسی")
    sub_phys_e = Subject(name="فیزیک تجربی")
    sub_chem_e = Subject(name="شیمی تجربی")
    sub_math_e = Subject(name="ریاضی تجربی")

    # Human track subjects
    sub_arab_h = Subject(name="عربی تخصصی")

    db.add_all([
        sub_calc, sub_geom, sub_disc, sub_phys_m, sub_chem_m,
        sub_bio, sub_phys_e, sub_chem_e, sub_math_e,
        sub_arab_h,
    ])
    db.flush()

    # Link to tracks
    track_math.subjects = [sub_calc, sub_geom, sub_disc, sub_phys_m, sub_chem_m]
    track_exp.subjects = [sub_bio, sub_phys_e, sub_chem_e, sub_math_e]
    track_hum.subjects = [sub_arab_h]
    db.flush()

    # Users
    tutor = User(
        username="tutor_lead",
        hashed_password="hash",
        role="TUTOR",
        full_name="Master Tutor",
        is_active=True,
    )
    student_11_math = User(
        username="stu_11_math",
        hashed_password="hash",
        role="STUDENT",
        full_name="Ali Math 11",
        grade="11",
        academic_track_id=track_math.id,
        is_active=True,
    )
    student_10_exp = User(
        username="stu_10_exp",
        hashed_password="hash",
        role="STUDENT",
        full_name="Sara Exp 10",
        grade="10",
        academic_track_id=track_exp.id,
        is_active=True,
    )
    student_12_hum = User(
        username="stu_12_hum",
        hashed_password="hash",
        role="STUDENT",
        full_name="Reza Hum 12",
        grade="12",
        academic_track_id=track_hum.id,
        is_active=True,
    )
    db.add_all([tutor, student_11_math, student_10_exp, student_12_hum])
    db.commit()

    return {
        "tracks": {"math": track_math, "exp": track_exp, "hum": track_hum},
        "subjects": {
            "calc": sub_calc, "geom": sub_geom, "disc": sub_disc,
            "phys_m": sub_phys_m, "chem_m": sub_chem_m,
            "bio": sub_bio, "phys_e": sub_phys_e, "chem_e": sub_chem_e, "math_e": sub_math_e,
            "arab_h": sub_arab_h,
        },
        "users": {
            "tutor": tutor,
            "stu_11_math": student_11_math,
            "stu_10_exp": student_10_exp,
            "stu_12_hum": student_12_hum,
        },
    }


def test_workflow_1_create_exam_series(db: Session, test_setup):
    """Workflow 1: Create external exam series."""
    start_d = date(2026, 9, 11)  # Friday
    end_d = date(2027, 6, 20)
    exam = create_exam(
        db,
        title="قلم‌چی آزمون‌های آزمایشی ۱۴۰۵-۱۴۰۶",
        description="آزمون‌های جامع دو هفته یکبار",
        first_exam_date=start_d,
        last_exam_date=end_d,
        recurrence_interval_weeks=2,
        recurrence_weekday=4,  # Friday in Python weekday() is 4
    )
    assert exam.id is not None
    assert exam.title == "قلم‌چی آزمون‌های آزمایشی ۱۴۰۵-۱۴۰۶"
    assert exam.recurrence_interval_weeks == 2
    assert exam.recurrence_weekday == 4
    assert exam.first_exam_date == start_d
    assert exam.last_exam_date == end_d


def test_workflow_2_and_3_grade_track_and_reporting_groups(db: Session, test_setup):
    """
    Workflow 2: Configure multiple grade/track combinations.
    Workflow 3: Configure different reporting groups for each combination.
    """
    exam = create_exam(db, title="گزینه دو آزمون‌های جامع", recurrence_interval_weeks=2)
    track_math = test_setup["tracks"]["math"]
    track_exp = test_setup["tracks"]["exp"]
    s = test_setup["subjects"]

    # 1. Configure Grade 11 Mathematics with grouped subjects:
    # ریاضی combines calc, geom, disc
    # فیزیک has phys_m
    # شیمی has chem_m
    math_groups = [
        {"title": "ریاضی", "order_index": 1, "subject_ids": [s["calc"].id, s["geom"].id, s["disc"].id]},
        {"title": "فیزیک", "order_index": 2, "subject_ids": [s["phys_m"].id]},
        {"title": "شیمی", "order_index": 3, "subject_ids": [s["chem_m"].id]},
    ]
    cfg_math = configure_exam_grade_track(
        db,
        exam_id=exam.id,
        grade="11",
        track_id=track_math.id,
        reporting_groups_data=math_groups,
    )
    assert cfg_math.grade == "11"
    assert cfg_math.track_id == track_math.id
    assert len(cfg_math.reporting_groups) == 3
    grp_math_combined = next(rg for rg in cfg_math.reporting_groups if rg.title == "ریاضی")
    assert len(grp_math_combined.subjects) == 3

    # 2. Configure Grade 10 Experimental with single-subject reporting groups
    exp_groups = [
        {"title": "زیست‌شناسی", "order_index": 1, "subject_ids": [s["bio"].id]},
        {"title": "شیمی", "order_index": 2, "subject_ids": [s["chem_e"].id]},
        {"title": "فیزیک", "order_index": 3, "subject_ids": [s["phys_e"].id]},
        {"title": "ریاضی تجربی", "order_index": 4, "subject_ids": [s["math_e"].id]},
    ]
    cfg_exp = configure_exam_grade_track(
        db,
        exam_id=exam.id,
        grade="10",
        track_id=track_exp.id,
        reporting_groups_data=exp_groups,
    )
    assert cfg_exp.grade == "10"
    assert cfg_exp.track_id == track_exp.id
    assert len(cfg_exp.reporting_groups) == 4

    # Verify both configurations coexist independently on the same series
    fetched_exam = get_exam_by_id(db, exam.id)
    assert len(fetched_exam.grade_track_configs) == 2

    # 3. Verify a subject (e.g. حسابان) CAN be assigned to multiple reporting groups without error
    multi_group_config = [
        {"title": "حسابان تخصصی", "order_index": 1, "subject_ids": [s["calc"].id]},
        {"title": "ریاضی جامع", "order_index": 2, "subject_ids": [s["calc"].id, s["geom"].id]},
    ]
    cfg_multi = configure_exam_grade_track(
        db,
        exam_id=exam.id,
        grade="12",
        track_id=track_math.id,
        reporting_groups_data=multi_group_config,
    )
    assert len(cfg_multi.reporting_groups) == 2
    assert s["calc"] in cfg_multi.reporting_groups[0].subjects
    assert s["calc"] in cfg_multi.reporting_groups[1].subjects


def test_workflow_4_biweekly_recurrence(db: Session, test_setup):
    """Workflow 4: Generate biweekly schedule (every 2 weeks)."""
    start_d = date(2026, 10, 2)  # Friday
    end_d = date(2026, 11, 30)
    dates = calculate_recurring_dates(
        first_exam_date=start_d,
        last_exam_date=end_d,
        interval_weeks=2,
        weekday=6,  # 6 is Friday in Valhalla WEEKDAY_MAPPING
    )
    # Expected: Oct 2, Oct 16, Oct 30, Nov 13, Nov 27
    assert dates == [
        date(2026, 10, 2),
        date(2026, 10, 16),
        date(2026, 10, 30),
        date(2026, 11, 13),
        date(2026, 11, 27),
    ]
    assert len(dates) == 5
    for i in range(len(dates) - 1):
        assert (dates[i + 1] - dates[i]).days == 14


def test_workflow_5_and_6_three_week_anchor_recurrence(db: Session, test_setup):
    """
    Workflow 5: Generate three-week recurring schedule.
    Workflow 6: Verify recurrence is anchored to the first exam date (strictly 21 days between exams).
    """
    start_d = date(2026, 9, 11)  # Friday
    end_d = date(2026, 11, 30)
    dates = calculate_recurring_dates(
        first_exam_date=start_d,
        last_exam_date=end_d,
        interval_weeks=3,
        weekday=6,  # 6 is Friday in Valhalla WEEKDAY_MAPPING
    )
    # Strictly 21 days between exams
    for i in range(len(dates) - 1):
        assert (dates[i + 1] - dates[i]).days == 21

    # Check exact dates
    assert dates[0] == date(2026, 9, 11)
    assert dates[1] == date(2026, 10, 2)
    assert dates[2] == date(2026, 10, 23)
    assert dates[3] == date(2026, 11, 13)


def test_workflow_7_8_9_10_exceptions_skip_restore_manual(db: Session, test_setup):
    """
    Workflow 7: Skip one date without shifting later dates.
    Workflow 8: Skip multiple dates with audit logging.
    Workflow 9: Restore a skipped date.
    Workflow 10: Add a manual replacement occurrence.
    """
    tutor = test_setup["users"]["tutor"]
    exam = create_exam(
        db,
        title="قلم‌چی سری تست استثنائات",
        first_exam_date=date(2026, 9, 4),
        last_exam_date=date(2026, 11, 20),
        recurrence_interval_weeks=2,
        recurrence_weekday=6,
    )
    configure_exam_grade_track(
        db,
        exam_id=exam.id,
        grade="11",
        track_id=test_setup["tracks"]["math"].id,
        reporting_groups_data=[{"title": "ریاضی", "order_index": 1, "subject_ids": [test_setup["subjects"]["calc"].id]}],
    )
    sessions = generate_series_sessions(
        db,
        exam_id=exam.id,
        dates=[
            date(2026, 9, 4),
            date(2026, 9, 18),
            date(2026, 10, 2),
            date(2026, 10, 16),
            date(2026, 10, 30),
            date(2026, 11, 13),
        ],
        actor_id=tutor.id,
    )
    assert len(sessions) == 6

    # Workflow 7: Skip October 2 (Holiday). Check that later dates do not shift!
    oct_2_sess = next(s for s in sessions if s.date == date(2026, 10, 2))
    skipped_oct_2 = skip_exam_session(
        db,
        session_id=oct_2_sess.id,
        actor_id=tutor.id,
        reason="Official Public Holiday",
    )
    assert skipped_oct_2.status == "SKIPPED"
    assert skipped_oct_2.skip_reason == "Official Public Holiday"

    # Verify subsequent dates remain unchanged
    all_sess = db.query(ExamSession).filter(ExamSession.exam_id == exam.id).order_by(ExamSession.date.asc()).all()
    dates_list = [s.date for s in all_sess]
    assert dates_list == [
        date(2026, 9, 4),
        date(2026, 9, 18),
        date(2026, 10, 2),
        date(2026, 10, 16),
        date(2026, 10, 30),
        date(2026, 11, 13),
    ]

    # Workflow 8: Skip another date (November 13 - Institute Schedule Change)
    nov_13_sess = next(s for s in sessions if s.date == date(2026, 11, 13))
    skip_exam_session(
        db,
        session_id=nov_13_sess.id,
        actor_id=tutor.id,
        reason="Institute Schedule Postponed",
    )
    db.refresh(nov_13_sess)
    assert nov_13_sess.status == "SKIPPED"

    # Verify audit logs for both skips
    audits = db.query(ExamSessionAudit).filter(ExamSessionAudit.action == "SKIPPED").all()
    assert len(audits) >= 2
    assert any(a.reason == "Official Public Holiday" and a.actor_id == tutor.id for a in audits)

    # Workflow 9: Restore October 2
    restored_oct_2 = restore_exam_session(
        db,
        session_id=oct_2_sess.id,
        actor_id=tutor.id,
        reason="Holiday Cancelled by Ministry",
    )
    assert restored_oct_2.status == "SCHEDULED"
    assert restored_oct_2.skip_reason is None

    # Workflow 10: Add a manual replacement occurrence on Thursday Oct 8
    manual_sess = add_manual_replacement_session(
        db,
        exam_id=exam.id,
        exam_date=date(2026, 10, 8),
        title="جبرانی پنجشنبه",
        actor_id=tutor.id,
    )
    assert manual_sess.is_manually_added is True
    assert manual_sess.date == date(2026, 10, 8)
    assert manual_sess.status == "SCHEDULED"


def test_workflow_11_edit_future_recurrence_preserves_past_results(db: Session, test_setup):
    """
    Workflow 11: Edit future recurrence rules without modifying or deleting past completed occurrences or submitted results.
    """
    tutor = test_setup["users"]["tutor"]
    stu_math = test_setup["users"]["stu_11_math"]
    track_math = test_setup["tracks"]["math"]
    s = test_setup["subjects"]

    exam = create_exam(
        db,
        title="سری آزمون‌های پاییزی",
        first_exam_date=date(2026, 9, 4),
        last_exam_date=date(2026, 10, 30),
        recurrence_interval_weeks=2,
        recurrence_weekday=6,
    )
    configure_exam_grade_track(
        db,
        exam_id=exam.id,
        grade="11",
        track_id=track_math.id,
        reporting_groups_data=[
            {"title": "ریاضی", "order_index": 1, "subject_ids": [s["calc"].id]},
        ],
    )
    sessions = generate_series_sessions(
        db,
        exam_id=exam.id,
        dates=[date(2026, 9, 4), date(2026, 9, 18), date(2026, 10, 2)],
        actor_id=tutor.id,
    )
    assign_exam_series_to_students(db, exam.id, [stu_math.id])

    # Student submits result for past occurrence (Sept 4)
    past_session = sessions[0]
    submit_student_exam_result(
        db,
        student=stu_math,
        exam_session_id=past_session.id,
        group_data=[{"group_title": "ریاضی", "percentage": 88.5}],
        overall_rank=12,
        notes="First exam taken",
    )

    # Now tutor changes recurrence for future dates: switch to every 3 weeks
    new_sessions = update_future_recurrence(
        db,
        exam_id=exam.id,
        new_interval_weeks=3,
        new_first_date=date(2026, 9, 25),
        new_last_date=date(2026, 11, 20),
        new_weekday=6,
        actor_id=tutor.id,
    )

    # Verify past session (Sept 4) and its result are intact!
    db.refresh(past_session)
    assert past_session.status == "SCHEDULED"
    result = db.query(StudentExamResult).filter(StudentExamResult.exam_session_id == past_session.id).first()
    assert result is not None
    assert result.overall_rank == 12
    assert result.group_results[0].percentage == 88.5


def test_workflow_12_13_14_assignment_and_automatic_synchronization(db: Session, test_setup):
    """
    Workflow 12: Assign series to students from different grades and tracks.
    Workflow 13: Automatically select correct reporting configuration for each student.
    Workflow 14: Reject incompatible students on assignment.
    """
    exam = create_exam(db, title="گزینه دو سراسری")
    track_math = test_setup["tracks"]["math"]
    track_exp = test_setup["tracks"]["exp"]
    s = test_setup["subjects"]

    # Configure Grade 11 Math and Grade 10 Exp
    configure_exam_grade_track(
        db,
        exam_id=exam.id,
        grade="11",
        track_id=track_math.id,
        reporting_groups_data=[{"title": "حسابان و هندسه", "order_index": 1, "subject_ids": [s["calc"].id, s["geom"].id]}],
    )
    configure_exam_grade_track(
        db,
        exam_id=exam.id,
        grade="10",
        track_id=track_exp.id,
        reporting_groups_data=[{"title": "زیست شناسی تجربی", "order_index": 1, "subject_ids": [s["bio"].id]}],
    )

    stu_math = test_setup["users"]["stu_11_math"]
    stu_exp = test_setup["users"]["stu_10_exp"]
    stu_hum = test_setup["users"]["stu_12_hum"]

    # Workflow 14: Evaluate eligibility before assignment - stu_hum is incompatible
    eval_res = evaluate_students_eligibility(db, exam.id, [stu_math.id, stu_exp.id, stu_hum.id])
    assert len(eval_res["eligible"]) == 2
    assert len(eval_res["ineligible"]) == 1
    assert eval_res["ineligible"][0]["student_id"] == stu_hum.id

    # Trying to assign incompatible student raises ExamValidationError
    with pytest.raises(ExamValidationError) as exc_info:
        assign_exam_series_to_students(db, exam.id, [stu_math.id, stu_hum.id])
    assert "not eligible" in str(exc_info.value)

    # Workflow 12: Assign eligible students
    assign_res = assign_exam_series_to_students(db, exam.id, [stu_math.id, stu_exp.id])
    assert assign_res["assigned_count"] == 2

    # Workflow 13: Automatically select correct reporting configuration for each student
    cfg_for_math = get_student_series_grade_track_config(db, exam.id, stu_math)
    assert cfg_for_math is not None
    assert cfg_for_math.grade == "11"
    assert cfg_for_math.reporting_groups[0].title == "حسابان و هندسه"

    cfg_for_exp = get_student_series_grade_track_config(db, exam.id, stu_exp)
    assert cfg_for_exp is not None
    assert cfg_for_exp.grade == "10"
    assert cfg_for_exp.reporting_groups[0].title == "زیست شناسی تجربی"


def test_workflow_15_academic_profile_change_reevaluation(db: Session, test_setup):
    """
    Workflow 15: Re-evaluate future eligibility after student changes grade/track without modifying historical results.
    """
    exam = create_exam(db, title="کانون قلم‌چی سالانه")
    track_math = test_setup["tracks"]["math"]
    track_hum = test_setup["tracks"]["hum"]
    s = test_setup["subjects"]

    configure_exam_grade_track(
        db,
        exam_id=exam.id,
        grade="11",
        track_id=track_math.id,
        reporting_groups_data=[{"title": "ریاضیات", "order_index": 1, "subject_ids": [s["calc"].id]}],
    )
    stu_math = test_setup["users"]["stu_11_math"]
    assign_exam_series_to_students(db, exam.id, [stu_math.id])

    # Currently compatible
    incompatible_before = check_student_series_eligibility(db, stu_math.id)
    assert len(incompatible_before) == 0

    # Student transitions to Grade 12 or switches track to Humanities
    stu_math.grade = "12"
    stu_math.academic_track_id = track_hum.id
    db.commit()

    # System detects student is no longer compatible
    incompatible_after = check_student_series_eligibility(db, stu_math.id)
    assert len(incompatible_after) == 1
    assert "no longer configured" in incompatible_after[0]["reason"]

    # System-wide tutor alerts list
    all_alerts = get_all_series_incompatible_students(db)
    assert len(all_alerts) >= 1
    target_alert = next(a for a in all_alerts if a["student_id"] == str(stu_math.id))
    assert target_alert is not None

    # Tutor dismisses future assignments
    dismiss_series_incompatible_assignment(db, uuid.UUID(target_alert["assignment_id"]))
    assert len(check_student_series_eligibility(db, stu_math.id)) == 0


def test_workflow_16_calendar_and_14_day_plan_integration(db: Session, test_setup):
    """
    Workflow 16: Display only applicable scheduled occurrences in student exam list and 14-day study plan.
    Skipped or cancelled occurrences must NOT appear as active upcoming exams.
    """
    exam = create_exam(db, title="آزمون سنجش پیش‌دانشگاهی")
    track_exp = test_setup["tracks"]["exp"]
    s = test_setup["subjects"]
    stu_exp = test_setup["users"]["stu_10_exp"]

    configure_exam_grade_track(
        db,
        exam_id=exam.id,
        grade="10",
        track_id=track_exp.id,
        reporting_groups_data=[{"title": "زیست", "order_index": 1, "subject_ids": [s["bio"].id]}],
    )

    today = date.today()
    s1 = create_exam_session(db, exam_id=exam.id, exam_date=today + timedelta(days=3), status="SCHEDULED")
    s2 = create_exam_session(db, exam_id=exam.id, exam_date=today + timedelta(days=10), status="SKIPPED", is_manually_added=False)
    s3 = create_exam_session(db, exam_id=exam.id, exam_date=today + timedelta(days=17), status="SCHEDULED")

    assign_exam_series_to_students(db, exam.id, [stu_exp.id])

    # 1. Check student available exams view: s2 (SKIPPED) must NOT appear in upcoming!
    avail = get_student_available_exams(db, stu_exp)
    upcoming_session_ids = [item["session"].id for item in avail["upcoming"]]
    assert s1.id in upcoming_session_ids
    assert s2.id not in upcoming_session_ids
    assert s3.id in upcoming_session_ids

    # 2. Check 14-day study plan integration
    plan_exams = get_student_external_exams_in_date_range(
        db,
        student=stu_exp,
        start_date=today,
        end_date=today + timedelta(days=14),
    )
    # s1 (3 days ahead) must be included
    assert (today + timedelta(days=3)) in plan_exams
    # s2 (10 days ahead, SKIPPED) must NOT be included in active plan
    assert (today + timedelta(days=10)) not in plan_exams
    # s3 (17 days ahead) is beyond 14 days, so not in this range
    assert (today + timedelta(days=17)) not in plan_exams


def test_workflow_17_result_submission_with_snapshot_and_groups(db: Session, test_setup):
    """
    Workflow 17: Submit percentages per reporting group, rank, notes, and report card attachment.
    Preserves immutable configuration snapshot.
    """
    exam = create_exam(db, title="گزینه دو مرحله ۳")
    track_math = test_setup["tracks"]["math"]
    s = test_setup["subjects"]
    stu_math = test_setup["users"]["stu_11_math"]

    configure_exam_grade_track(
        db,
        exam_id=exam.id,
        grade="11",
        track_id=track_math.id,
        reporting_groups_data=[
            {"title": "ریاضیات پایه و گسسته", "order_index": 1, "subject_ids": [s["calc"].id, s["disc"].id]},
            {"title": "فیزیک", "order_index": 2, "subject_ids": [s["phys_m"].id]},
        ],
    )
    sess = create_exam_session(db, exam_id=exam.id, exam_date=date(2026, 10, 15))
    assign_exam_series_to_students(db, exam.id, [stu_math.id])

    # Student submits results
    group_data = [
        {"group_title": "ریاضیات پایه و گسسته", "percentage": 75.5, "included_subject_names": "حسابان، گسسته"},
        {"group_title": "فیزیک", "percentage": 82.0, "included_subject_names": "فیزیک ریاضی"},
    ]
    res = submit_student_exam_result(
        db,
        student=stu_math,
        exam_session_id=sess.id,
        group_data=group_data,
        overall_rank=45,
        notes="Math was challenging, physics was good",
        report_card_file_path="report_cards/sample_card.pdf",
        report_card_file_name="sample_card.pdf",
    )
    assert res.id is not None
    assert res.overall_rank == 45
    assert res.notes == "Math was challenging, physics was good"
    assert res.report_card_file_name == "sample_card.pdf"
    assert res.config_snapshot is not None
    assert "ریاضیات پایه و گسسته" in res.config_snapshot

    # Check group results
    assert len(res.group_results) == 2
    g1 = next(g for g in res.group_results if g.group_title == "ریاضیات پایه و گسسته")
    assert g1.percentage == 75.5

    # Test editing the result
    updated_groups = [
        {"reporting_group_id": g1.reporting_group_id, "group_title": "ریاضیات پایه و گسسته", "percentage": 78.0},
        {"group_title": "فیزیک", "percentage": 85.0},
    ]
    updated = update_student_exam_result(
        db,
        student=stu_math,
        result_id=res.id,
        group_data=updated_groups,
        overall_rank=40,
        notes="Corrected review score",
    )
    assert updated.overall_rank == 40
    assert updated.notes == "Corrected review score"
    g1_updated = next(g for g in updated.group_results if g.group_title == "ریاضیات پایه و گسسته")
    assert g1_updated.percentage == 78.0


def test_workflow_18_and_19_historical_results_and_isolation(db: Session, test_setup):
    """
    Workflow 18 & 19: Allow tutor to access results and report card; preserve separation between External Exams, Practice Exams, and Historical Results.
    """
    stu_math = test_setup["users"]["stu_11_math"]
    track_math = test_setup["tracks"]["math"]

    # Historical result record
    hist = create_historical_exam_result(
        db,
        student_id=stu_math.id,
        exam_name="قلم‌چی تابستانه ۱۴۰۴",
        exam_date=date(2025, 8, 20),
        subject_scores=[{"subject_name": "حسابان", "percentage": 90.0}],
        overall_rank=15,
        notes="Pre-entry diagnostic exam",
        report_card_file_path="report_cards/hist_card.pdf",
        report_card_file_name="hist_card.pdf",
    )
    assert hist.id is not None
    assert hist.exam_name == "قلم‌چی تابستانه ۱۴۰۴"
    assert hist.overall_rank == 15
    assert len(hist.subject_results) == 1
    assert hist.subject_results[0].percentage == 90.0

    # Verify Historical Results are in separate table and don't pollute ExternalExam or ExamSession
    assert db.query(Exam).filter(Exam.title == "قلم‌چی تابستانه ۱۴۰۴").first() is None
    assert db.query(ExamSession).filter(ExamSession.title == "قلم‌چی تابستانه ۱۴۰۴").first() is None
