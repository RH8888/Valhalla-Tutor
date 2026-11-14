import uuid
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import pytest
from sqlalchemy.orm import Session

from app.core.timezone import now_utc
from app.models.subject import Subject
from app.models.track import AcademicTrack
from app.models.exam import (
    Exam,
    ExamGradeTrackConfig,
    ExamReportingGroup,
    ExamSession,
    StudentExamGroupResult,
    StudentExamResult,
    ExamAuditLog,
    ExternalExamAssignment,
)
from app.models.user import User, UserRole
from app.services.exam_service import (
    ExamNotFoundError,
    ExamSessionNotFoundError,
    ExamValidationError,
    IneligibleStudentError,
    archive_exam,
    bulk_add_manual_sessions,
    bulk_assign_occurrences_to_students,
    bulk_cancel_exam_sessions,
    bulk_remove_students_from_future_occurrences,
    bulk_restore_exam_sessions,
    bulk_skip_exam_sessions,
    cancel_exam_session,
    compare_students_on_session,
    configure_exam_grade_track,
    create_exam,
    delete_exam_session,
    extend_exam_recurrence,
    generate_series_sessions,
    get_bulk_series_submission_overview,
    get_exam_series_analytics,
    get_student_comprehensive_analytics,
    list_exam_audit_logs,
    mark_exam_result_reviewed,
    reopen_exam_result,
    restore_archived_exam_series,
    safe_delete_exam_series,
    submit_student_exam_result,
    tutor_correct_exam_result,
)


@pytest.fixture
def db(db_session: Session) -> Session:
    return db_session


@pytest.fixture
def workflow_setup(db: Session):
    # Tracks
    track_math = AcademicTrack(name="Mathematics")
    track_exp = AcademicTrack(name="Experimental")
    db.add_all([track_math, track_exp])
    db.flush()

    # Subjects
    sub_calc = Subject(name="حسابان")
    sub_geom = Subject(name="هندسه")
    sub_phys = Subject(name="فیزیک")
    sub_chem = Subject(name="شیمی")
    sub_bio = Subject(name="زیست")
    db.add_all([sub_calc, sub_geom, sub_phys, sub_chem, sub_bio])
    db.flush()

    track_math.subjects = [sub_calc, sub_geom, sub_phys, sub_chem]
    track_exp.subjects = [sub_bio, sub_phys, sub_chem]
    db.flush()

    # Users
    tutor = User(
        username="tutor_lead",
        email="lead@tutor.valhalla",
        hashed_password="pw",
        role=UserRole.TUTOR,
        full_name="Lead Tutor",
        is_active=True,
    )
    s1 = User(
        username="student_1",
        email="s1@valhalla.local",
        hashed_password="pw",
        role=UserRole.STUDENT,
        grade="یازدهم",
        academic_track_id=track_math.id,
        full_name="Math Student 1",
        is_active=True,
    )
    s2 = User(
        username="student_2",
        email="s2@valhalla.local",
        hashed_password="pw",
        role=UserRole.STUDENT,
        grade="یازدهم",
        academic_track_id=track_math.id,
        full_name="Math Student 2",
        is_active=True,
    )
    s3 = User(
        username="student_3",
        email="s3@valhalla.local",
        hashed_password="pw",
        role=UserRole.STUDENT,
        grade="دهم",
        academic_track_id=track_exp.id,
        full_name="Exp Student 3",
        is_active=True,
    )
    db.add_all([tutor, s1, s2, s3])
    db.commit()

    return {
        "tutor": tutor,
        "track_math": track_math,
        "track_exp": track_exp,
        "sub_calc": sub_calc,
        "sub_geom": sub_geom,
        "sub_phys": sub_phys,
        "sub_chem": sub_chem,
        "sub_bio": sub_bio,
        "s1": s1,
        "s2": s2,
        "s3": s3,
    }


def test_exam_lifecycle_deadlines_and_review(db: Session, workflow_setup):
    tutor = workflow_setup["tutor"]
    s1 = workflow_setup["s1"]
    track_math = workflow_setup["track_math"]
    sub_calc = workflow_setup["sub_calc"]
    sub_phys = workflow_setup["sub_phys"]

    # 1. Create series
    exam = create_exam(
        db,
        title="Lifecycle & Review Series",
        is_active=True,
        first_exam_date=date.today() - timedelta(days=5),
        last_exam_date=date.today() + timedelta(days=20),
        recurrence_interval_weeks=1,
        submission_days_after_exam=3,
        actor_id=tutor.id,
    )
    # Configure Grade/Track
    cfg = configure_exam_grade_track(
        db,
        exam_id=exam.id,
        grade="یازدهم",
        track_id=track_math.id,
        groups=[
            {"title": "ریاضی", "subjects": [sub_calc.id], "sequence_order": 1},
            {"title": "فیزیک", "subjects": [sub_phys.id], "sequence_order": 2},
        ],
    )
    sessions = generate_series_sessions(db, exam.id)
    assert len(sessions) > 0
    sess = sessions[0]  # past session: date = 5 days ago
    assert sess.status == "SCHEDULED"

    # Deadline is exam_date + 3 days = 2 days ago. Overdue!
    deadline = sess.submission_deadline
    if deadline and deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    assert deadline is not None
    assert deadline < now_utc()
    grp_math = cfg.reporting_groups[0]
    grp_phys = cfg.reporting_groups[1]

    # Attempt submission with allow_late_submission = False
    sess.allow_late_submission = False
    db.commit()

    with pytest.raises(ExamValidationError, match="Submission deadline has passed"):
        submit_student_exam_result(
            db,
            exam_session_id=sess.id,
            student_id=s1.id,
            group_percentages={grp_math.id: 85.0, grp_phys.id: 70.0},
        )

    # Allow late submission
    sess.allow_late_submission = True
    db.commit()

    res = submit_student_exam_result(
        db,
        exam_session_id=sess.id,
        student_id=s1.id,
        group_percentages={grp_math.id: 85.0, grp_phys.id: 70.0},
        overall_rank=42,
    )
    assert res.is_late is True
    assert res.is_reviewed is False

    # Review result
    reviewed_res = mark_exam_result_reviewed(db, res.id, tutor_id=tutor.id)
    assert reviewed_res.is_reviewed is True
    assert reviewed_res.reviewed_by_id == tutor.id
    assert reviewed_res.reviewed_at is not None

    # Reopen result
    reopened_res = reopen_exam_result(db, res.id, tutor_id=tutor.id, reason="Student sent revised score")
    assert reopened_res.is_reviewed is False

    # Tutor corrects result
    corrected_res = tutor_correct_exam_result(
        db,
        res.id,
        tutor_id=tutor.id,
        group_percentages={grp_math.id: 90.0, grp_phys.id: 75.0},
        overall_rank=35,
        reason="Verified against official paper key",
    )
    assert corrected_res.is_tutor_corrected is True
    assert corrected_res.overall_rank == 35


def test_bulk_student_assignment_and_removal(db: Session, workflow_setup):
    tutor = workflow_setup["tutor"]
    s1 = workflow_setup["s1"]
    s2 = workflow_setup["s2"]
    s3 = workflow_setup["s3"]
    track_math = workflow_setup["track_math"]
    sub_calc = workflow_setup["sub_calc"]

    exam = create_exam(
        db,
        title="Bulk Assignment Series",
        is_active=True,
        first_exam_date=date.today() - timedelta(days=7),
        last_exam_date=date.today() + timedelta(days=21),
        recurrence_interval_weeks=1,
    )
    cfg = configure_exam_grade_track(
        db,
        exam_id=exam.id,
        grade="یازدهم",
        track_id=track_math.id,
        groups=[{"title": "حسابان", "subjects": [sub_calc.id], "sequence_order": 1}],
    )
    sessions = generate_series_sessions(db, exam.id)
    assert len(sessions) >= 4

    past_sess = sessions[0]
    future_sess = sessions[1]

    # Ineligible student assignment should fail validation
    with pytest.raises(IneligibleStudentError):
        bulk_assign_occurrences_to_students(db, [future_sess.id], [s3.id], actor_id=tutor.id)

    # Valid bulk assignment
    res_assign = bulk_assign_occurrences_to_students(
        db, [past_sess.id, future_sess.id], [s1.id, s2.id], actor_id=tutor.id
    )
    assert res_assign["assigned_count"] == 4

    # Submit result on past session for s1
    grp_id = cfg.reporting_groups[0].id
    submit_student_exam_result(
        db,
        exam_session_id=past_sess.id,
        student_id=s1.id,
        group_percentages={grp_id: 88.0},
    )

    # Bulk remove s1 and s2 from future occurrences
    remove_res = bulk_remove_students_from_future_occurrences(
        db, exam.id, [s1.id, s2.id], actor_id=tutor.id
    )
    assert remove_res["affected_students_count"] == 2

    # Check that s1's past result on past_sess is strictly preserved!
    s1_past_res = db.query(StudentExamResult).filter_by(
        exam_session_id=past_sess.id, student_id=s1.id
    ).first()
    assert s1_past_res is not None

    # Check future assignment was removed
    s1_future_assign = db.query(ExternalExamAssignment).filter_by(
        exam_session_id=future_sess.id, student_id=s1.id
    ).first()
    assert s1_future_assign is None


def test_bulk_occurrence_operations_and_schedule_extension(db: Session, workflow_setup):
    tutor = workflow_setup["tutor"]
    track_math = workflow_setup["track_math"]
    sub_calc = workflow_setup["sub_calc"]
    exam = create_exam(
        db,
        title="Occurrence Operations Series",
        is_active=True,
        first_exam_date=date.today(),
        last_exam_date=date.today() + timedelta(days=14),
        recurrence_interval_weeks=1,
    )
    configure_exam_grade_track(
        db,
        exam_id=exam.id,
        grade="یازدهم",
        track_id=track_math.id,
        groups=[{"title": "حسابان", "subjects": [sub_calc.id], "sequence_order": 1}],
    )
    sessions = generate_series_sessions(db, exam.id)
    assert len(sessions) == 3

    s_ids = [s.id for s in sessions[:2]]

    # Bulk skip
    skip_res = bulk_skip_exam_sessions(db, s_ids, actor_id=tutor.id, reason="National holidays")
    assert skip_res["affected_count"] == 2
    for sid in s_ids:
        sess = db.query(ExamSession).get(sid)
        assert sess.status == "SKIPPED"
        assert sess.skip_reason == "National holidays"

    # Bulk restore
    restore_res = bulk_restore_exam_sessions(db, s_ids, actor_id=tutor.id, reason="Session resumed")
    assert restore_res["affected_count"] == 2
    for sid in s_ids:
        sess = db.query(ExamSession).get(sid)
        assert sess.status == "SCHEDULED"

    # Bulk cancel
    cancel_res = bulk_cancel_exam_sessions(db, s_ids, actor_id=tutor.id, reason="Cancelled by institute")
    assert cancel_res["affected_count"] == 2
    for sid in s_ids:
        sess = db.query(ExamSession).get(sid)
        assert sess.status == "CANCELLED"

    # Extend recurrence schedule to later end date
    new_end_date = date.today() + timedelta(days=28)
    extended = extend_exam_recurrence(db, exam.id, new_end_date, actor_id=tutor.id)
    assert len(extended) >= 2


def test_safe_editing_deletion_and_archiving(db: Session, workflow_setup):
    tutor = workflow_setup["tutor"]
    s1 = workflow_setup["s1"]
    track_math = workflow_setup["track_math"]
    sub_calc = workflow_setup["sub_calc"]

    exam = create_exam(
        db,
        title="Safe Delete Series",
        is_active=True,
        first_exam_date=date.today(),
        last_exam_date=date.today() + timedelta(days=7),
        recurrence_interval_weeks=1,
    )
    cfg = configure_exam_grade_track(
        db,
        exam_id=exam.id,
        grade="یازدهم",
        track_id=track_math.id,
        groups=[{"title": "حسابان", "subjects": [sub_calc.id], "sequence_order": 1}],
    )
    sessions = generate_series_sessions(db, exam.id)
    sess = sessions[0]

    # Archiving and restoring
    archived = archive_exam(db, exam.id, actor_id=tutor.id)
    assert archived.is_active is False
    assert archived.is_archived is True

    # Restoring
    restored = restore_archived_exam_series(db, exam.id, actor_id=tutor.id)
    assert restored.is_active is True
    assert restored.is_archived is False

    # Submit result
    submit_student_exam_result(
        db,
        exam_session_id=sess.id,
        student_id=s1.id,
        group_percentages={cfg.reporting_groups[0].id: 79.0},
    )

    # Session deletion must be safely BLOCKED because results exist!
    with pytest.raises(ExamValidationError, match="submitted student results"):
        delete_exam_session(db, sess.id, actor_id=tutor.id)

    # Exam series deletion must be safely BLOCKED because results exist!
    with pytest.raises(ExamValidationError, match="submitted student results"):
        safe_delete_exam_series(db, exam.id, actor_id=tutor.id)

    # Cancellation should work cleanly instead of hard deletion
    cancelled_sess = cancel_exam_session(db, sess.id, actor_id=tutor.id, reason="Postponed")
    assert cancelled_sess.status == "CANCELLED"


def test_audit_history_and_student_group_comparison(db: Session, workflow_setup):
    tutor = workflow_setup["tutor"]
    s1 = workflow_setup["s1"]
    s2 = workflow_setup["s2"]
    track_math = workflow_setup["track_math"]
    sub_calc = workflow_setup["sub_calc"]

    exam = create_exam(
        db,
        title="Comparison & Audit Series",
        is_active=True,
        first_exam_date=date.today(),
        last_exam_date=date.today() + timedelta(days=7),
        recurrence_interval_weeks=1,
    )
    cfg = configure_exam_grade_track(
        db,
        exam_id=exam.id,
        grade="یازدهم",
        track_id=track_math.id,
        groups=[{"title": "حسابان", "subjects": [sub_calc.id], "sequence_order": 1}],
    )
    sessions = generate_series_sessions(db, exam.id)
    sess = sessions[0]

    # Assign both students
    bulk_assign_occurrences_to_students(db, [sess.id], [s1.id, s2.id], actor_id=tutor.id)

    # s1 submits score 80
    grp_id = cfg.reporting_groups[0].id
    r1 = submit_student_exam_result(
        db,
        exam_session_id=sess.id,
        student_id=s1.id,
        group_percentages={grp_id: 80.0},
        overall_rank=100,
    )
    # Tutor corrects s1's score to 85
    tutor_correct_exam_result(
        db,
        r1.id,
        tutor_id=tutor.id,
        group_percentages={grp_id: 85.0},
        overall_rank=90,
        reason="Key error adjusted",
    )

    # s2 does NOT submit (missing result!)

    # Run group comparison on this session
    comp = compare_students_on_session(db, session_id=sess.id, grade="یازدهم", track_id=track_math.id)
    assert comp["total_assigned"] == 2
    assert comp["submitted_count"] == 1
    assert comp["missing_count"] == 1

    # Missing results must NEVER be treated as zero percent!
    # Therefore, the group average for 'حسابان' should be 85.0 (only from s1), NOT (85+0)/2 = 42.5!
    assert comp["group_averages"]["حسابان"] == 85.0
    assert comp["average_rank"] == 90.0

    # Verify student row states
    row_s1 = [r for r in comp["rows"] if r["student_id"] == str(s1.id)][0]
    row_s2 = [r for r in comp["rows"] if r["student_id"] == str(s2.id)][0]

    assert row_s1["submission_status"] == "Submitted"
    assert row_s1["result_type"] == "Tutor-Corrected"

    assert row_s2["submission_status"] == "Missing"
    assert row_s2["result_type"] == "N/A"
    assert row_s2["average_percentage"] is None  # NOT ZERO!

    # Verify audit logs
    audit_logs = list_exam_audit_logs(db, exam_id=exam.id)
    assert len(audit_logs) > 0
    actions = [l.action for l in audit_logs]
    assert "CORRECTED" in actions


def test_student_comprehensive_analytics_trends_and_progression(db: Session, workflow_setup):
    s1 = workflow_setup["s1"]
    track_math = workflow_setup["track_math"]
    sub_calc = workflow_setup["sub_calc"]

    exam = create_exam(
        db,
        title="Progression Series",
        is_active=True,
        first_exam_date=date.today() - timedelta(days=28),
        last_exam_date=date.today(),
        recurrence_interval_weeks=1,
    )
    cfg = configure_exam_grade_track(
        db,
        exam_id=exam.id,
        grade="یازدهم",
        track_id=track_math.id,
        groups=[{"title": "حسابان", "subjects": [sub_calc.id], "sequence_order": 1}],
    )
    sessions = generate_series_sessions(db, exam.id)
    grp_id = cfg.reporting_groups[0].id

    # 1 exam result -> Trend should indicate insufficient data (requires >= 3 results)
    submit_student_exam_result(
        db,
        exam_session_id=sessions[0].id,
        student_id=s1.id,
        group_percentages={grp_id: 60.0},
        overall_rank=200,
    )
    analytics_1 = get_student_comprehensive_analytics(db, s1.id, exam_id=exam.id)
    assert analytics_1["group_stats"]["حسابان"]["trend"] == "Insufficient data"
    assert analytics_1["group_stats"]["حسابان"]["is_sufficient_data"] is False

    # Submit 2 more results with increasing scores: 60 -> 70 -> 80
    submit_student_exam_result(
        db,
        exam_session_id=sessions[1].id,
        student_id=s1.id,
        group_percentages={grp_id: 70.0},
        overall_rank=150,
    )
    submit_student_exam_result(
        db,
        exam_session_id=sessions[2].id,
        student_id=s1.id,
        group_percentages={grp_id: 80.0},
        overall_rank=100,
    )

    analytics_3 = get_student_comprehensive_analytics(db, s1.id, exam_id=exam.id)
    assert analytics_3["group_stats"]["حسابان"]["is_sufficient_data"] is True
    assert analytics_3["group_stats"]["حسابان"]["trend"] == "Improving"

    # Consecutive comparisons
    assert len(analytics_3["consecutive_comparisons"]) == 3
    c2 = analytics_3["consecutive_comparisons"][1]
    assert c2["change_from_previous"] == 10.0

    # Best and weakest
    assert analytics_3["group_stats"]["حسابان"]["best"] == 80.0
    assert analytics_3["group_stats"]["حسابان"]["weakest"] == 60.0
