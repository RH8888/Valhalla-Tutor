from datetime import date, time, timedelta
from pathlib import Path
from typing import Dict
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import SESSION_COOKIE_NAME
from app.models.exam import ExamSeriesAssignment, ExternalExamAssignment
from app.models.meeting import MeetingRescheduleHistory, MeetingStatus, MeetingType, TutorMeeting
from app.models.plan import CompletionAuditAction, CompletionAuditLog, PlanAssignment, PlanStatus, TaskType
from app.models.user import User
from app.services.academic_service import (
    assign_student_track,
    create_subject,
    create_track,
    customize_student_subjects,
)
from app.services.auth_service import create_session
from app.services.exam_service import (
    ExamValidationError,
    archive_exam,
    assign_exam_series_to_students,
    assign_external_exam_to_students,
    bulk_assign_occurrences_to_students,
    bulk_cancel_exam_sessions,
    bulk_restore_exam_sessions,
    bulk_skip_exam_sessions,
    cancel_exam_session,
    configure_exam_grade_track,
    create_exam,
    create_exam_session,
    delete_exam_grade_track_config,
    extend_exam_recurrence,
    generate_series_sessions,
    mark_exam_result_reviewed,
    restore_exam_session,
    skip_exam_session,
    submit_student_exam_result,
    update_exam,
    update_exam_session,
    update_future_recurrence,
    update_student_exam_result,
)
from app.services.meeting_service import (
    MeetingValidationError,
    create_meeting,
    reschedule_meeting,
    update_meeting_status,
)
from app.services.plan_service import (
    PlanValidationError,
    archive_study_plan,
    complete_assignment,
    create_assignment,
    create_study_plan,
    delete_assignment,
    delete_study_plan,
    publish_study_plan,
    reset_assignment_completion,
    undo_assignment_completion,
)
from app.services.practice_exam_service import (
    PracticeExamValidationError,
    add_practice_exam_booklet,
    configure_practice_exam_questions,
    create_practice_exam,
    start_practice_attempt,
    submit_booklet_answers,
)
from app.services.user_service import create_student
from tests.conftest import TestingSessionLocal


# ---------------------------------------------------------------------------
# Phase 1: Practice Exams (#1)
# ---------------------------------------------------------------------------


def test_add_booklet_blocked_after_in_progress_or_completed_attempt(
    client: TestClient,
    db_session: Session,
    tutor_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Finding #1: Adding a booklet must fail once any student attempt has started."""
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))

    sub = create_subject(db_session, name=f"PE_Sub_{uuid.uuid4().hex[:6]}", grades=["11"])
    track = create_track(db_session, name=f"PE_Track_{uuid.uuid4().hex[:6]}", subject_ids=[sub.id])
    student = create_student(
        db_session,
        username=f"pe_stu_{uuid.uuid4().hex[:6]}",
        full_name="PE Student",
        password="Password123!",
        grade="11",
    )
    student = assign_student_track(db_session, student.id, track.id)

    exam = create_practice_exam(
        db_session,
        title="Single Booklet Exam",
        grade="11",
        academic_track_id=track.id,
        is_timed=False,
    )
    b1 = add_practice_exam_booklet(
        db_session,
        practice_exam_id=exam.id,
        title="Booklet 1",
        pdf_file_path="practice_booklets/b1.pdf",
        pdf_file_name="b1.pdf",
        question_start=1,
        question_end=2,
    )
    configure_practice_exam_questions(
        db_session,
        exam.id,
        [
            {"question_number": 1, "correct_choice": 1, "subject_id": sub.id},
            {"question_number": 2, "correct_choice": 2, "subject_id": sub.id},
        ],
    )

    attempt = start_practice_attempt(db_session, student, exam.id)

    # 1. Service call cannot add Booklet 2 while an attempt is IN_PROGRESS
    with pytest.raises(PracticeExamValidationError):
        add_practice_exam_booklet(
            db_session,
            practice_exam_id=exam.id,
            title="Sneaky Booklet 2",
            pdf_file_path="practice_booklets/b2.pdf",
            pdf_file_name="b2.pdf",
            question_start=3,
            question_end=4,
        )

    # 2. HTTP upload endpoint must reject and leave no orphaned booklet PDF on disk
    token_t, sess_t = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, token_t)
    resp = client.post(
        f"/tutor/practice-exams/{exam.id}/booklets",
        data={
            "csrf_token": sess_t.csrf_token,
            "title": "Sneaky Booklet 2",
            "question_start": "3",
            "question_end": "4",
        },
        files={"file": ("b2.pdf", b"%PDF-1.4\ntest", "application/pdf")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "err=" in resp.headers["location"]
    assert (list((tmp_path / "practice_booklets").glob("*")) if (tmp_path / "practice_booklets").exists() else []) == []

    # 3. Student's in-progress attempt still finishes cleanly on Booklet 1 alone
    res = submit_booklet_answers(
        db_session,
        student=student,
        attempt_id=attempt.id,
        booklet_id=b1.id,
        answers={1: 1, 2: 2},
        advance_to_next=True,
    )
    assert res["completed"] is True
    db_session.refresh(attempt)
    assert attempt.status == "COMPLETED"
    assert attempt.overall_percentage == 100.0

    # 4. Still blocked even after attempt is COMPLETED (preserves historical/retake structure)
    with pytest.raises(PracticeExamValidationError):
        add_practice_exam_booklet(
            db_session,
            practice_exam_id=exam.id,
            title="Post-Completion Booklet",
            pdf_file_path="practice_booklets/b3.pdf",
            pdf_file_name="b3.pdf",
            question_start=3,
            question_end=4,
        )



# ---------------------------------------------------------------------------
# Phase 2: External Exams (#2 - #6)
# ---------------------------------------------------------------------------


def _setup_exam_phase2(db: Session):
    sub_math = create_subject(db, name=f"ExMath_{uuid.uuid4().hex[:6]}", grades=["11"])
    sub_phys = create_subject(db, name=f"ExPhys_{uuid.uuid4().hex[:6]}", grades=["11"])
    track = create_track(db, name=f"ExTrack_{uuid.uuid4().hex[:6]}", subject_ids=[sub_math.id, sub_phys.id])
    s1 = create_student(db, username=f"ex1_{uuid.uuid4().hex[:6]}", full_name="Ex Student 1", password="Password123!", grade="11")
    s1 = assign_student_track(db, s1.id, track.id)
    s2 = create_student(db, username=f"ex2_{uuid.uuid4().hex[:6]}", full_name="Ex Student 2", password="Password123!", grade="11")
    s2 = assign_student_track(db, s2.id, track.id)
    return sub_math, sub_phys, track, s1, s2


def test_restore_and_bulk_restore_cannot_reopen_cancelled_occurrences(client: TestClient, db_session: Session, tutor_session):
    """Finding #2: CANCELLED is terminal and cannot be reopened via bulk/single restore or skip->restore."""
    sub_math, _, track, _, _ = _setup_exam_phase2(db_session)
    exam = create_exam(db_session, title="Restore Guard Exam")
    s_skip = create_exam_session(db_session, exam.id, date(2026, 11, 5), track_subjects_map={track.id: [sub_math.id]})
    s_cancel = create_exam_session(db_session, exam.id, date(2026, 11, 12), track_subjects_map={track.id: [sub_math.id]})

    skip_exam_session(db_session, s_skip.id, reason="Holiday")
    cancel_exam_session(db_session, s_cancel.id, reason="Cancelled permanently")

    # Direct single restore fails on CANCELLED
    with pytest.raises(ExamValidationError):
        restore_exam_session(db_session, s_cancel.id)

    # Attempting to bypass CANCELLED -> SKIPPED -> SCHEDULED must fail
    with pytest.raises(ExamValidationError):
        skip_exam_session(db_session, s_cancel.id)
    bulk_skip_exam_sessions(db_session, [s_cancel.id])
    db_session.refresh(s_cancel)
    assert s_cancel.status == "CANCELLED"

    # Bulk restore restores s_skip ONLY, leaving s_cancel CANCELLED
    res = bulk_restore_exam_sessions(db_session, [s_skip.id, s_cancel.id], reason="Bulk reopen")
    assert res["affected_count"] == 1
    db_session.refresh(s_skip)
    db_session.refresh(s_cancel)
    assert s_skip.status == "SCHEDULED"
    assert s_cancel.status == "CANCELLED"

    # HTTP bulk/restore endpoint and single restore endpoint preserve terminal state
    token_t, sess_t = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, token_t)
    resp = client.post(
        "/tutor/exams/sessions/bulk/action",
        data={
            "csrf_token": sess_t.csrf_token,
            "exam_id": str(exam.id),
            "bulk_action": "restore",
            "session_ids": [str(s_cancel.id)],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db_session.refresh(s_cancel)
    assert s_cancel.status == "CANCELLED"

    resp_single = client.post(
        f"/tutor/exams/sessions/{s_cancel.id}/restore",
        data={"csrf_token": sess_t.csrf_token},
        follow_redirects=False,
    )
    assert resp_single.status_code == 303
    assert "err=" in resp_single.headers["location"]
    db_session.refresh(s_cancel)
    assert s_cancel.status == "CANCELLED"


def test_student_result_update_refreshes_after_review_locking(db_session: Session, tutor_user: User):
    """Finding #3: Even if a stale result object was already loaded in session before lock, review lock rejects edit."""
    sub_math, _, track, s1, _ = _setup_exam_phase2(db_session)
    exam = create_exam(db_session, title="Review Race Exam")
    sess = create_exam_session(db_session, exam.id, date(2026, 11, 10), track_subjects_map={track.id: [sub_math.id]})

    res = submit_student_exam_result(
        db_session,
        student=s1,
        exam_session_id=sess.id,
        subject_data=[{"subject_id": sub_math.id, "correct_answers": 10, "incorrect_answers": 2, "percentage": 70.0}],
    )
    from sqlalchemy import update
    from app.models.exam import StudentExamResult

    assert res.is_reviewed is False
    db_session.execute(
        update(StudentExamResult)
        .where(StudentExamResult.id == res.id)
        .values(is_reviewed=True)
    )
    db_session.commit()

    # Stale ORM object in session identity map has is_reviewed=False; lock+populate_existing must reject
    with pytest.raises(ExamValidationError, match="reviewed or corrected"):
        update_student_exam_result(
            db_session,
            student=s1,
            result_id=res.id,
            subject_data=[{"subject_id": sub_math.id, "correct_answers": 20, "incorrect_answers": 0, "percentage": 100.0}],
        )


def test_series_assignment_form_revokes_omitted_students_preserving_results(
    client: TestClient, db_session: Session, tutor_session
):
    """Finding #4: Unchecking students on series assignment form revokes omitted assignments but keeps submitted results."""
    sub_math, _, track, s1, s2 = _setup_exam_phase2(db_session)
    exam = create_exam(db_session, title="Revoke Omitted Exam")
    cfg = configure_exam_grade_track(
        db_session,
        exam.id,
        grade="11",
        track_id=track.id,
        reporting_groups_data=[{"title": "Math", "subject_ids": [sub_math.id]}],
    )
    past_sess = create_exam_session(db_session, exam.id, date(2026, 10, 1), track_subjects_map={track.id: [sub_math.id]})
    future_sess = create_exam_session(db_session, exam.id, date(2099, 1, 15), track_subjects_map={track.id: [sub_math.id]})

    token_t, sess_t = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, token_t)

    # Step 1: Assign both s1 and s2 via form
    resp1 = client.post(
        f"/tutor/exams/{exam.id}/assignments",
        data={"csrf_token": sess_t.csrf_token, "student_ids": [str(s1.id), str(s2.id)]},
        follow_redirects=False,
    )
    assert resp1.status_code == 303
    assert db_session.query(ExamSeriesAssignment).filter(ExamSeriesAssignment.exam_id == exam.id).count() == 2

    # s2 submits past_sess
    submit_student_exam_result(
        db_session,
        student=s2,
        exam_session_id=past_sess.id,
        group_data=[{"reporting_group_id": cfg.reporting_groups[0].id, "group_title": "Math", "percentage": 85.0}],
    )

    # Step 2: Resubmit form with ONLY s1 checked (s2 omitted/unchecked) -> s2 must be revoked
    resp2 = client.post(
        f"/tutor/exams/{exam.id}/assignments",
        data={"csrf_token": sess_t.csrf_token, "student_ids": [str(s1.id)]},
        follow_redirects=False,
    )
    assert resp2.status_code == 303

    assigned_sids = {sa.student_id for sa in db_session.query(ExamSeriesAssignment).filter(ExamSeriesAssignment.exam_id == exam.id).all()}
    assert assigned_sids == {s1.id}

    # s2's unsubmitted future session assignment is removed, while s2's submitted past_sess assignment/result remain
    assert db_session.query(ExternalExamAssignment).filter_by(exam_session_id=future_sess.id, student_id=s2.id).first() is None
    assert db_session.query(ExternalExamAssignment).filter_by(exam_session_id=past_sess.id, student_id=s2.id).first() is not None

    # Step 3: Submit form with ALL unchecked (no student_ids field at all) -> s1 also revoked
    resp3 = client.post(
        f"/tutor/exams/{exam.id}/assignments",
        data={"csrf_token": sess_t.csrf_token},
        follow_redirects=False,
    )
    assert resp3.status_code == 303
    assert db_session.query(ExamSeriesAssignment).filter(ExamSeriesAssignment.exam_id == exam.id).count() == 0
    assert db_session.query(ExternalExamAssignment).filter_by(exam_session_id=future_sess.id, student_id=s1.id).first() is None


def test_archived_exam_series_blocks_configuration_and_assignments(db_session: Session, tutor_user: User):
    """Finding #5: Archived exam series rejects edits, grade-track configs, session generation, and assignments."""
    sub_math, _, track, s1, _ = _setup_exam_phase2(db_session)
    exam = create_exam(
        db_session,
        title="Archive Guard Series",
        first_exam_date=date(2026, 11, 1),
        last_exam_date=date(2026, 12, 1),
        recurrence_interval_weeks=2,
    )
    cfg = configure_exam_grade_track(
        db_session,
        exam.id,
        grade="11",
        track_id=track.id,
        reporting_groups_data=[{"title": "Math", "subject_ids": [sub_math.id]}],
    )
    sess = create_exam_session(db_session, exam.id, date(2026, 11, 5), track_subjects_map={track.id: [sub_math.id]})

    archive_exam(db_session, exam.id, actor_id=tutor_user.id)

    with pytest.raises(ExamValidationError):
        update_exam(db_session, exam.id, title="Renamed")
    with pytest.raises(ExamValidationError):
        configure_exam_grade_track(
            db_session,
            exam.id,
            grade="11",
            track_id=track.id,
            reporting_groups_data=[{"title": "New", "subject_ids": [sub_math.id]}],
        )
    with pytest.raises(ExamValidationError):
        delete_exam_grade_track_config(db_session, cfg.id, exam_id=exam.id)
    with pytest.raises(ExamValidationError):
        update_exam_session(db_session, sess.id, date(2026, 11, 6), title="Moved")
    with pytest.raises(ExamValidationError):
        generate_series_sessions(db_session, exam.id, dates=[date(2026, 11, 15)])
    with pytest.raises(ExamValidationError):
        update_future_recurrence(db_session, exam.id, 1, date(2026, 11, 1), date(2026, 12, 1))
    with pytest.raises(ExamValidationError):
        extend_exam_recurrence(db_session, exam.id, date(2027, 1, 1))
    with pytest.raises(ExamValidationError):
        assign_exam_series_to_students(db_session, exam.id, [s1.id])
    with pytest.raises(ExamValidationError):
        assign_external_exam_to_students(db_session, sess.id, [s1.id])
    with pytest.raises(ExamValidationError):
        bulk_assign_occurrences_to_students(db_session, [sess.id], [s1.id])


def test_student_exam_subject_authorization_fails_closed_on_empty_effective_set(db_session: Session):
    """Finding #6: Empty student effective subjects or empty intersection must fail closed."""
    sub_math, sub_phys, track, s1, s2 = _setup_exam_phase2(db_session)
    exam = create_exam(db_session, title="Fail Closed Subject Auth")
    sess = create_exam_session(
        db_session,
        exam.id,
        date(2026, 11, 5),
        track_subjects_map={track.id: [sub_math.id, sub_phys.id]},
    )

    s1 = customize_student_subjects(db_session, s1.id, [])
    with pytest.raises(ExamValidationError, match="not allowed"):
        submit_student_exam_result(
            db_session,
            student=s1,
            exam_session_id=sess.id,
            subject_data=[{"subject_id": sub_math.id, "correct_answers": 5, "incorrect_answers": 0, "percentage": 50.0}],
        )

    res2 = submit_student_exam_result(
        db_session,
        student=s2,
        exam_session_id=sess.id,
        subject_data=[{"subject_id": sub_math.id, "correct_answers": 5, "incorrect_answers": 0, "percentage": 50.0}],
    )
    s2 = customize_student_subjects(db_session, s2.id, [])
    with pytest.raises(ExamValidationError, match="not allowed"):
        update_student_exam_result(
            db_session,
            student=s2,
            result_id=res2.id,
            subject_data=[{"subject_id": sub_math.id, "correct_answers": 10, "incorrect_answers": 0, "percentage": 100.0}],
        )



# ---------------------------------------------------------------------------
# Phase 3: Study Plans & Assignments (#7-#12)
# ---------------------------------------------------------------------------


def _setup_plan_phase3(db: Session, tutor: User):
    sub = create_subject(db, name=f"PlanSub_{uuid.uuid4().hex[:6]}", grades=["11"])
    track = create_track(db, name=f"PlanTrack_{uuid.uuid4().hex[:6]}", subject_ids=[sub.id])
    student = create_student(
        db,
        username=f"p3s_{uuid.uuid4().hex[:6]}",
        full_name="Phase3 Student",
        password="Password123!",
        grade="11",
    )
    assign_student_track(db, student.id, track.id)
    plan = create_study_plan(db, student.id, tutor.id, date(2026, 11, 2), title="Phase 3 Plan")
    return sub, student, plan


def test_delete_assignment_refreshes_stale_orm_and_blocks_newly_completed(
    db_session: Session, tutor_user: User
):
    """Finding #7: Stale in-session ORM must not allow deleting a newly completed assignment."""
    sub, student, plan = _setup_plan_phase3(db_session, tutor_user)
    assignment = create_assignment(
        db_session,
        plan.id,
        plan.start_date,
        sub.id,
        TaskType.CUSTOM,
        30,
        title="Race Task",
        tutor_id=tutor_user.id,
    )
    publish_study_plan(db_session, plan.id, tutor_id=tutor_user.id)

    # Load stale uncompleted ORM state into db_session's identity map
    stale = db_session.query(PlanAssignment).filter_by(id=assignment.id).first()
    assert stale is not None and stale.is_completed is False

    # Concurrent session marks the assignment completed in DB
    db2 = TestingSessionLocal()
    try:
        complete_assignment(db2, assignment.id, student.id, actual_duration_minutes=25)
    finally:
        db2.close()

    # Identity map still caches stale.is_completed == False until delete_assignment refreshes
    with pytest.raises(PlanValidationError, match="completed"):
        delete_assignment(db_session, assignment.id, tutor_id=tutor_user.id)

    assert db_session.query(PlanAssignment).filter_by(id=assignment.id).first() is not None


def test_student_cannot_call_tutor_reset_while_stage6_undo_requires_published_own_plan(
    client: TestClient, db_session: Session, tutor_user: User
):
    """Finding #8: Students stay blocked (403) from tutor reset while Stage-6 own undo preserves audits."""
    sub, student, plan = _setup_plan_phase3(db_session, tutor_user)
    other_student = create_student(
        db_session,
        username=f"p3other_{uuid.uuid4().hex[:6]}",
        full_name="Other Student",
        password="Password123!",
        grade="11",
    )
    assignment = create_assignment(
        db_session,
        plan.id,
        plan.start_date,
        sub.id,
        TaskType.CUSTOM,
        30,
        title="Undo Boundary Task",
        tutor_id=tutor_user.id,
    )
    publish_study_plan(db_session, plan.id, tutor_id=tutor_user.id)

    tok_s, sess_s = create_session(db_session, student)
    tok_other, sess_other = create_session(db_session, other_student)

    resp_comp = client.post(
        f"/student/assignments/{assignment.id}/complete",
        data={"actual_duration_minutes": "20", "csrf_token": sess_s.csrf_token},
        cookies={SESSION_COOKIE_NAME: tok_s},
    )
    assert resp_comp.status_code == 200

    # Student cannot invoke tutor-only reset endpoint
    resp_tutor_reset = client.post(
        f"/tutor/assignments/{assignment.id}/reset-completion",
        data={"csrf_token": sess_s.csrf_token},
        cookies={SESSION_COOKIE_NAME: tok_s},
    )
    assert resp_tutor_reset.status_code == 403

    # Another student cannot invoke undo on this student's assignment
    resp_other_undo = client.post(
        f"/student/assignments/{assignment.id}/undo",
        data={"csrf_token": sess_other.csrf_token},
        cookies={SESSION_COOKIE_NAME: tok_other},
    )
    assert resp_other_undo.status_code == 403

    # Owning student can legitimately undo on active PUBLISHED plan and audit trail records STUDENT_UNDO
    resp_undo = client.post(
        f"/student/assignments/{assignment.id}/undo",
        data={"csrf_token": sess_s.csrf_token},
        cookies={SESSION_COOKIE_NAME: tok_s},
    )
    assert resp_undo.status_code == 200

    db_session.expire_all()
    refreshed = db_session.query(PlanAssignment).filter_by(id=assignment.id).first()
    assert refreshed is not None and refreshed.is_completed is False
    actions = [
        row.action
        for row in db_session.query(CompletionAuditLog)
        .filter_by(assignment_id=assignment.id)
        .order_by(CompletionAuditLog.created_at)
        .all()
    ]
    assert actions == [CompletionAuditAction.COMPLETED, CompletionAuditAction.STUDENT_UNDO]


def test_cannot_erase_completion_audit_history_by_resetting_then_deleting(
    client: TestClient, db_session: Session, tutor_user: User, tutor_session
):
    """Finding #9: Assignments and draft plans with audit logs cannot be deleted; DB FK restricts cascade delete."""
    tok_t, sess_t = tutor_session
    sub, student, plan = _setup_plan_phase3(db_session, tutor_user)
    a_reset = create_assignment(
        db_session, plan.id, plan.start_date, sub.id, TaskType.CUSTOM, 30, title="Reset Protected", tutor_id=tutor_user.id
    )
    a_undone = create_assignment(
        db_session, plan.id, plan.start_date, sub.id, TaskType.CUSTOM, 25, title="Undo Protected", tutor_id=tutor_user.id
    )
    publish_study_plan(db_session, plan.id, tutor_id=tutor_user.id)

    complete_assignment(db_session, a_reset.id, student.id, actual_duration_minutes=30)
    reset_assignment_completion(db_session, a_reset.id, tutor_user.id, note="mistake")

    complete_assignment(db_session, a_undone.id, student.id, actual_duration_minutes=25)
    undo_assignment_completion(db_session, a_undone.id, student.id)

    # Service and HTTP route block deleting reset or undone assignments with audit history
    with pytest.raises(PlanValidationError, match="audit history"):
        delete_assignment(db_session, a_reset.id, tutor_id=tutor_user.id)
    with pytest.raises(PlanValidationError, match="audit history"):
        delete_assignment(db_session, a_undone.id, tutor_id=tutor_user.id)

    resp_http = client.post(
        f"/tutor/plans/assignments/{a_reset.id}/delete",
        data={"csrf_token": sess_t.csrf_token},
        cookies={SESSION_COOKIE_NAME: tok_t},
        follow_redirects=False,
    )
    assert resp_http.status_code == 400
    assert db_session.query(CompletionAuditLog).filter_by(assignment_id=a_reset.id).count() == 2
    assert db_session.query(CompletionAuditLog).filter_by(assignment_id=a_undone.id).count() == 2

    # Draft plan with historical audit entry also cannot be deleted via delete_study_plan
    draft_plan = create_study_plan(db_session, student.id, tutor_user.id, date(2026, 12, 1), title="Draft Audit Plan")
    a_draft = create_assignment(
        db_session, draft_plan.id, draft_plan.start_date, sub.id, TaskType.CUSTOM, 15, title="Draft Audited", tutor_id=tutor_user.id
    )
    complete_assignment(db_session, a_draft.id, student.id, actual_duration_minutes=15)
    reset_assignment_completion(db_session, a_draft.id, tutor_user.id, note="cleanup")
    with pytest.raises(PlanValidationError, match="audit history"):
        delete_study_plan(db_session, draft_plan.id, tutor_id=tutor_user.id)

    # DB-level FK RESTRICT enforcement (SQLite needs PRAGMA foreign_keys=ON; PostgreSQL enforces natively)
    db_session.execute(text("PRAGMA foreign_keys=ON"))
    try:
        db_session.delete(a_reset)
        with pytest.raises(IntegrityError):
            db_session.flush()
    finally:
        db_session.rollback()
        db_session.execute(text("PRAGMA foreign_keys=OFF"))


def test_tutor_reset_blocked_on_archived_study_plan(
    client: TestClient, db_session: Session, tutor_user: User, tutor_session
):
    """Finding #10: Tutor cannot reset assignment completion once the study plan is archived."""
    tok_t, sess_t = tutor_session
    sub, student, plan = _setup_plan_phase3(db_session, tutor_user)
    assignment = create_assignment(
        db_session, plan.id, plan.start_date, sub.id, TaskType.CUSTOM, 30, title="Archive Reset Guard", tutor_id=tutor_user.id
    )
    publish_study_plan(db_session, plan.id, tutor_id=tutor_user.id)
    complete_assignment(db_session, assignment.id, student.id, actual_duration_minutes=30)
    archive_study_plan(db_session, plan.id, tutor_id=tutor_user.id)

    with pytest.raises(PlanValidationError, match="archived"):
        reset_assignment_completion(db_session, assignment.id, tutor_user.id, note="late edit")

    resp = client.post(
        f"/tutor/assignments/{assignment.id}/reset-completion",
        data={"note": "bypass attempt", "csrf_token": sess_t.csrf_token},
        cookies={SESSION_COOKIE_NAME: tok_t},
    )
    assert resp.status_code == 400
    assert db_session.query(CompletionAuditLog).filter_by(assignment_id=assignment.id).count() == 1


def test_complete_and_undo_blocked_after_plan_archival_even_with_stale_orm(
    client: TestClient, db_session: Session, tutor_user: User
):
    """Findings #11 & #12: Complete and undo lock/refresh plan row and block once archived."""
    sub, student, plan = _setup_plan_phase3(db_session, tutor_user)
    a_pending = create_assignment(
        db_session, plan.id, plan.start_date, sub.id, TaskType.CUSTOM, 30, title="Pending Before Archive", tutor_id=tutor_user.id
    )
    a_done = create_assignment(
        db_session, plan.id, plan.start_date, sub.id, TaskType.CUSTOM, 20, title="Done Before Archive", tutor_id=tutor_user.id
    )
    publish_study_plan(db_session, plan.id, tutor_id=tutor_user.id)
    complete_assignment(db_session, a_done.id, student.id, actual_duration_minutes=20)

    # Pre-load stale PUBLISHED plan state into db_session's identity map
    stale_pending = db_session.query(PlanAssignment).filter_by(id=a_pending.id).first()
    stale_done = db_session.query(PlanAssignment).filter_by(id=a_done.id).first()
    assert stale_pending.study_plan.status == PlanStatus.PUBLISHED
    assert stale_done.study_plan.status == PlanStatus.PUBLISHED

    # Another transaction archives the plan
    db2 = TestingSessionLocal()
    try:
        archive_study_plan(db2, plan.id, tutor_id=tutor_user.id)
    finally:
        db2.close()

    with pytest.raises(PlanValidationError, match="archived"):
        complete_assignment(db_session, a_pending.id, student.id, actual_duration_minutes=30)

    with pytest.raises(PlanValidationError, match="archived"):
        undo_assignment_completion(db_session, a_done.id, student.id)

    tok_s, sess_s = create_session(db_session, student)
    resp_c = client.post(
        f"/student/assignments/{a_pending.id}/complete",
        data={"actual_duration_minutes": "30", "csrf_token": sess_s.csrf_token},
        cookies={SESSION_COOKIE_NAME: tok_s},
    )
    resp_u = client.post(
        f"/student/assignments/{a_done.id}/undo",
        data={"csrf_token": sess_s.csrf_token},
        cookies={SESSION_COOKIE_NAME: tok_s},
    )
    assert resp_c.status_code == 403
    assert resp_u.status_code == 403


# ---------------------------------------------------------------------------
# Phase 4: Meetings (#13)
# ---------------------------------------------------------------------------


def test_terminal_meetings_cannot_be_reactivated_by_reschedule_or_quick_move(
    client: TestClient, db_session: Session, tutor_user: User, tutor_session
):
    """Finding #13: Terminal meetings (COMPLETED, CANCELLED, STUDENT_ABSENT) cannot be reactivated."""
    from app.services.scheduler_service import quick_move_meeting

    tok_t, sess_t = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, tok_t)
    headers = {"X-CSRF-Token": sess_t.csrf_token}

    student = create_student(
        db_session,
        username=f"p4s_{uuid.uuid4().hex[:6]}",
        full_name="Phase4 Student",
        password="Password123!",
        grade="11",
    )
    target_day = date(2026, 11, 20)
    move_day = date(2026, 11, 21)

    m_completed = create_meeting(
        db_session, tutor_user, student.id, target_day, time(9, 0), 60, MeetingType.ONLINE
    )
    update_meeting_status(db_session, m_completed.id, tutor_user, MeetingStatus.COMPLETED)

    m_cancelled = create_meeting(
        db_session, tutor_user, student.id, target_day, time(11, 0), 60, MeetingType.ONLINE
    )
    update_meeting_status(db_session, m_cancelled.id, tutor_user, MeetingStatus.CANCELLED)

    m_absent = create_meeting(
        db_session, tutor_user, student.id, target_day, time(13, 0), 60, MeetingType.ONLINE
    )
    update_meeting_status(db_session, m_absent.id, tutor_user, MeetingStatus.STUDENT_ABSENT)

    # 1. Direct service reschedule_meeting blocked for all terminal states
    for meeting_obj, expected_status in [
        (m_completed, MeetingStatus.COMPLETED),
        (m_cancelled, MeetingStatus.CANCELLED),
        (m_absent, MeetingStatus.STUDENT_ABSENT),
    ]:
        orig_start = meeting_obj.start_time
        with pytest.raises(MeetingValidationError, match="Cannot reschedule"):
            reschedule_meeting(
                db=db_session,
                meeting_id=meeting_obj.id,
                tutor=tutor_user,
                new_date=move_day,
                new_time_obj=time(15, 0),
                new_duration_minutes=45,
                reason="Bypass attempt",
            )
        db_session.refresh(meeting_obj)
        assert meeting_obj.status == expected_status
        assert meeting_obj.start_time == orig_start

    assert (
        db_session.query(MeetingRescheduleHistory)
        .filter(MeetingRescheduleHistory.meeting_id.in_([m_completed.id, m_cancelled.id, m_absent.id]))
        .count()
        == 0
    )

    # 2. Quick move (drag-and-drop / quick swap) also blocked for terminal meetings
    with pytest.raises(MeetingValidationError, match="Cannot reschedule"):
        quick_move_meeting(
            db_session, m_cancelled.id, tutor_user, move_day, "16:00", notify_student=False
        )

    # 3. Direct status transition back to SCHEDULED also blocked
    with pytest.raises(MeetingValidationError, match="reactivated"):
        update_meeting_status(db_session, m_completed.id, tutor_user, MeetingStatus.SCHEDULED)

    # 4. HTTP routes enforce 400 for reschedule, quick-move, and SCHEDULED reactivation
    r_resched = client.post(
        f"/tutor/meetings/{m_completed.id}/reschedule",
        data={
            "new_date": move_day.strftime("%Y-%m-%d"),
            "new_time": "16:00",
            "new_duration_minutes": "60",
            "reason": "HTTP bypass",
            "csrf_token": sess_t.csrf_token,
        },
        headers=headers,
    )
    assert r_resched.status_code == 400

    r_quick = client.post(
        f"/tutor/meetings/{m_cancelled.id}/quick-move",
        data={
            "target_date": move_day.strftime("%Y-%m-%d"),
            "target_time": "17:00",
            "csrf_token": sess_t.csrf_token,
        },
        headers=headers,
    )
    assert r_quick.status_code == 400

    r_status = client.post(
        f"/tutor/meetings/{m_absent.id}/status",
        data={"new_status": "SCHEDULED", "csrf_token": sess_t.csrf_token},
        headers=headers,
    )
    assert r_status.status_code == 400

    # 5. UI omits drag attribute on terminal meeting pills and omits reschedule controls in detail modal
    cal_resp = client.get(f"/tutor/calendar?view=month&date={target_day.strftime('%Y-%m-%d')}")
    assert cal_resp.status_code == 200
    assert f"handleMeetingDragStart(event, '{m_completed.id}')" not in cal_resp.text
    modal_resp = client.get(f"/tutor/meetings/{m_completed.id}")
    assert modal_resp.status_code == 200
    assert "/reschedule" not in modal_resp.text
    assert "/quick-move" not in modal_resp.text


# ---------------------------------------------------------------------------
# Phase 5: Sibling Workflow Hardening
# ---------------------------------------------------------------------------


def test_practice_exam_assignment_form_revokes_omitted_students(
    client: TestClient, db_session: Session, tutor_session
):
    """Sibling of #4: Practice exam assignment checkboxes must revoke unchecked direct assignments."""
    from app.models.practice_exam import PracticeExamAssignment
    from app.services.practice_exam_service import assign_practice_exam_to_students

    tok_t, sess_t = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, tok_t)

    sub = create_subject(db_session, name=f"PE_SibSub_{uuid.uuid4().hex[:6]}", grades=["11"])
    track_main = create_track(db_session, name=f"PE_SibMain_{uuid.uuid4().hex[:6]}", subject_ids=[sub.id])
    track_other = create_track(db_session, name=f"PE_SibOther_{uuid.uuid4().hex[:6]}", subject_ids=[sub.id])

    s1 = create_student(
        db_session,
        username=f"pesib1_{uuid.uuid4().hex[:6]}",
        full_name="PE Sibling One",
        password="Password123!",
        grade="11",
    )
    s2 = create_student(
        db_session,
        username=f"pesib2_{uuid.uuid4().hex[:6]}",
        full_name="PE Sibling Two",
        password="Password123!",
        grade="11",
    )
    assign_student_track(db_session, s1.id, track_other.id)
    assign_student_track(db_session, s2.id, track_other.id)

    exam = create_practice_exam(db_session, title="Sibling Revoke PE", grade="11", academic_track_id=track_main.id)
    assign_practice_exam_to_students(db_session, exam.id, [s1.id, s2.id])
    assert db_session.query(PracticeExamAssignment).filter_by(practice_exam_id=exam.id).count() == 2

    # Uncheck s2 by submitting only s1
    resp1 = client.post(
        f"/tutor/practice-exams/{exam.id}/assign",
        data={"student_ids": str(s1.id), "csrf_token": sess_t.csrf_token},
        headers={"X-CSRF-Token": sess_t.csrf_token},
        follow_redirects=False,
    )
    assert resp1.status_code == 303
    kept_ids = {
        row.student_id for row in db_session.query(PracticeExamAssignment).filter_by(practice_exam_id=exam.id).all()
    }
    assert kept_ids == {s1.id}

    # Uncheck everyone
    resp2 = client.post(
        f"/tutor/practice-exams/{exam.id}/assign",
        data={"csrf_token": sess_t.csrf_token},
        headers={"X-CSRF-Token": sess_t.csrf_token},
        follow_redirects=False,
    )
    assert resp2.status_code == 303
    assert db_session.query(PracticeExamAssignment).filter_by(practice_exam_id=exam.id).count() == 0
