import uuid
from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.dependencies import SESSION_COOKIE_NAME
from app.models.plan import PlanAssignment, PlanStatus, StudyPlan, TaskType, CompletionAuditLog, CompletionAuditAction
from app.models.subject import Subject
from app.models.user import User
from app.services.academic_service import assign_student_track, create_subject, create_track, set_track_subjects
from app.services.auth_service import create_session
from app.services.plan_service import (
    complete_assignment,
    create_assignment,
    create_study_plan,
    publish_study_plan,
    archive_study_plan,
    reset_assignment_completion,
    get_assignment_audit_logs,
)
from app.services.user_service import create_student


@pytest.fixture
def stage5_setup(db_session: Session, tutor_user: User):
    """Setup subjects, tracks, students, and sessions for Stage 5 tests."""
    sub_math = create_subject(db_session, "Mathematics 5")
    sub_phys = create_subject(db_session, "Physics 5")
    track = create_track(db_session, "STEM Track 5")
    set_track_subjects(db_session, track.id, [sub_math.id, sub_phys.id])

    st1 = create_student(db_session, "student_s5_1", "Student One S5", "Pass123!", "st1_s5@valhalla.local")
    assign_student_track(db_session, st1.id, track.id)

    st2 = create_student(db_session, "student_s5_2", "Student Two S5", "Pass123!", "st2_s5@valhalla.local")
    assign_student_track(db_session, st2.id, track.id)

    token1, session1 = create_session(db_session, st1)
    token2, session2 = create_session(db_session, st2)

    return {
        "sub_math": sub_math,
        "sub_phys": sub_phys,
        "track": track,
        "st1": st1,
        "st2": st2,
        "token1": token1,
        "session1": session1,
        "token2": token2,
        "session2": session2,
    }


def test_student_dashboard_active_and_empty_state(client: TestClient, db_session: Session, tutor_user: User, stage5_setup):
    token1 = stage5_setup["token1"]
    st1 = stage5_setup["st1"]
    sub_math = stage5_setup["sub_math"]
    client.cookies.set(SESSION_COOKIE_NAME, token1)

    # 1. Without published plan: student sees empty state
    resp_empty = client.get("/student/dashboard")
    assert resp_empty.status_code == 200
    assert "No Active Study Plan Available" in resp_empty.text

    # 2. Tutor creates and publishes a plan starting today
    today = date.today()
    plan = create_study_plan(db_session, st1.id, tutor_user.id, today, title="Sprint Alpha")
    t1 = create_assignment(db_session, plan.id, today, sub_math.id, TaskType.CUSTOM, 45, title="Math Problem Set 1")
    t2 = create_assignment(db_session, plan.id, today + timedelta(days=1), sub_math.id, TaskType.CUSTOM, 60, title="Math Problem Set 2")
    publish_study_plan(db_session, plan.id)

    # 3. Student views dashboard with active plan
    resp_dash = client.get("/student/dashboard")
    assert resp_dash.status_code == 200
    assert "Sprint Alpha" in resp_dash.text or "Math Problem Set 1" in resp_dash.text
    assert "Today's Study Checklist" in resp_dash.text
    assert "Math Problem Set 1" in resp_dash.text
    assert "45 minutes" in resp_dash.text or "45m" in resp_dash.text
    assert "0%" in resp_dash.text  # 0 of 2 completed


def test_student_today_tasks_and_daily_totals(client: TestClient, db_session: Session, tutor_user: User, stage5_setup):
    token1 = stage5_setup["token1"]
    st1 = stage5_setup["st1"]
    sub_math = stage5_setup["sub_math"]
    sub_phys = stage5_setup["sub_phys"]
    client.cookies.set(SESSION_COOKIE_NAME, token1)

    today = date.today()
    plan = create_study_plan(db_session, st1.id, tutor_user.id, today, title="Workload Test Plan")
    a1 = create_assignment(db_session, plan.id, today, sub_math.id, TaskType.CUSTOM, 30, title="Calculus Review")
    a2 = create_assignment(db_session, plan.id, today, sub_phys.id, TaskType.CUSTOM, 50, title="Optics Questions")
    publish_study_plan(db_session, plan.id)

    resp = client.get("/student/dashboard")
    assert resp.status_code == 200
    # Today total duration should be 80 minutes (1 hour 20 minutes)
    assert "1 hour 20 minutes" in resp.text
    assert "Calculus Review" in resp.text
    assert "Optics Questions" in resp.text


def test_student_archived_plans_and_read_only(client: TestClient, db_session: Session, tutor_user: User, stage5_setup):
    token1 = stage5_setup["token1"]
    st1 = stage5_setup["st1"]
    sub_math = stage5_setup["sub_math"]
    client.cookies.set(SESSION_COOKIE_NAME, token1)

    today = date.today()
    plan = create_study_plan(db_session, st1.id, tutor_user.id, today - timedelta(days=20), title="Sprint Past")
    t1 = create_assignment(db_session, plan.id, today - timedelta(days=20), sub_math.id, TaskType.CUSTOM, 40, title="Old Task")
    publish_study_plan(db_session, plan.id)
    complete_assignment(db_session, t1.id, st1.id)
    archive_study_plan(db_session, plan.id)

    # Access plan history page
    resp_hist = client.get("/student/plans/history")
    assert resp_hist.status_code == 200
    assert "Sprint Past" in resp_hist.text
    assert "100%" in resp_hist.text
    assert "ARCHIVED" in resp_hist.text

    # Open archived plan detail: should be read-only
    resp_plan = client.get(f"/student/plans/{plan.id}")
    assert resp_plan.status_code == 200
    assert "Archived &bull; Read-Only" in resp_plan.text or "Read-Only" in resp_plan.text
    assert "Mark Complete" not in resp_plan.text


def test_cross_student_isolation(client: TestClient, db_session: Session, tutor_user: User, stage5_setup):
    token1 = stage5_setup["token1"]
    session1 = stage5_setup["session1"]
    token2 = stage5_setup["token2"]
    st1 = stage5_setup["st1"]
    st2 = stage5_setup["st2"]
    sub_math = stage5_setup["sub_math"]

    # Create plan for student 2
    plan2 = create_study_plan(db_session, st2.id, tutor_user.id, date.today(), title="Student 2 Secret Plan")
    t2 = create_assignment(db_session, plan2.id, date.today(), sub_math.id, TaskType.CUSTOM, 60, title="ST2 Math Task")
    publish_study_plan(db_session, plan2.id)

    # Student 1 logs in and attempts to access Student 2's plan
    client.cookies.set(SESSION_COOKIE_NAME, token1)
    resp_plan = client.get(f"/student/plans/{plan2.id}")
    assert resp_plan.status_code == 404

    # Student 1 attempts to complete Student 2's assignment
    resp_complete = client.post(
        f"/student/assignments/{t2.id}/complete",
        headers={"X-CSRF-Token": session1.csrf_token},
    )
    assert resp_complete.status_code == 403
    assert "Unauthorized" in resp_complete.text


def test_student_cannot_modify_assignments(client: TestClient, db_session: Session, tutor_user: User, stage5_setup):
    token1 = stage5_setup["token1"]
    session1 = stage5_setup["session1"]
    st1 = stage5_setup["st1"]
    sub_math = stage5_setup["sub_math"]
    client.cookies.set(SESSION_COOKIE_NAME, token1)

    plan = create_study_plan(db_session, st1.id, tutor_user.id, date.today(), title="Student Plan")
    task = create_assignment(db_session, plan.id, date.today(), sub_math.id, TaskType.CUSTOM, 30, title="Task To Modify")
    publish_study_plan(db_session, plan.id)

    # Student attempts tutor modification routes
    resp_edit = client.post(
        f"/tutor/plans/assignments/{task.id}/edit",
        data={"title": "Hacked Title", "recommended_duration_minutes": 5, "csrf_token": session1.csrf_token},
        headers={"X-CSRF-Token": session1.csrf_token},
    )
    assert resp_edit.status_code == 403

    resp_del = client.post(
        f"/tutor/plans/assignments/{task.id}/delete",
        data={"csrf_token": session1.csrf_token},
        headers={"X-CSRF-Token": session1.csrf_token},
    )
    assert resp_del.status_code == 403


def test_student_completion_history_and_timestamps(client: TestClient, db_session: Session, tutor_user: User, stage5_setup):
    token1 = stage5_setup["token1"]
    session1 = stage5_setup["session1"]
    st1 = stage5_setup["st1"]
    sub_math = stage5_setup["sub_math"]
    client.cookies.set(SESSION_COOKIE_NAME, token1)

    plan = create_study_plan(db_session, st1.id, tutor_user.id, date.today(), title="History Sprint")
    task = create_assignment(db_session, plan.id, date.today(), sub_math.id, TaskType.CUSTOM, 45, title="Geometry Proofs")
    publish_study_plan(db_session, plan.id)

    # 1. Complete task via student API
    resp_comp = client.post(
        f"/student/assignments/{task.id}/complete",
        headers={"X-CSRF-Token": session1.csrf_token},
    )
    assert resp_comp.status_code == 200

    # 2. View completion history
    resp_hist = client.get("/student/history")
    assert resp_hist.status_code == 200
    assert "Geometry Proofs" in resp_hist.text
    assert "Mathematics 5" in resp_hist.text
    assert "Recommended: 45m" in resp_hist.text
    assert "Understanding Your Study Metrics" in resp_hist.text


def test_tutor_monitoring_student_progress(client: TestClient, db_session: Session, tutor_user: User, tutor_session, stage5_setup):
    tutor_token, tutor_sess = tutor_session
    st1 = stage5_setup["st1"]
    sub_math = stage5_setup["sub_math"]
    sub_phys = stage5_setup["sub_phys"]

    # Create published plan for Student 1 starting 2 days ago
    two_days_ago = date.today() - timedelta(days=2)
    plan = create_study_plan(db_session, st1.id, tutor_user.id, two_days_ago, title="Monitoring Plan")
    t1 = create_assignment(db_session, plan.id, two_days_ago, sub_math.id, TaskType.CUSTOM, 60, title="Past Task 1")
    t2 = create_assignment(db_session, plan.id, two_days_ago + timedelta(days=1), sub_phys.id, TaskType.CUSTOM, 45, title="Past Task 2")
    t3 = create_assignment(db_session, plan.id, date.today() + timedelta(days=2), sub_math.id, TaskType.CUSTOM, 30, title="Future Task")
    publish_study_plan(db_session, plan.id)

    # Student only completed t1; t2 was due yesterday and is pending -> student is behind!
    complete_assignment(db_session, t1.id, st1.id)

    # Tutor logs in and monitors student
    client.cookies.set(SESSION_COOKIE_NAME, tutor_token)
    resp_detail = client.get(f"/tutor/students/{st1.id}")
    assert resp_detail.status_code == 200
    assert "Monitoring Plan" in resp_detail.text
    assert "Behind Planned Workload" in resp_detail.text
    assert "behind by <strong>1</strong> task" in resp_detail.text or "behind by 1 task" in resp_detail.text
    assert "Subject Completion Breakdown" in resp_detail.text
    assert "Daily Schedule Progress (14 Days)" in resp_detail.text


def test_tutor_reset_accidental_completion_with_audit(client: TestClient, db_session: Session, tutor_user: User, tutor_session, stage5_setup):
    tutor_token, tutor_sess = tutor_session
    token1 = stage5_setup["token1"]
    session1 = stage5_setup["session1"]
    st1 = stage5_setup["st1"]
    sub_math = stage5_setup["sub_math"]

    plan = create_study_plan(db_session, st1.id, tutor_user.id, date.today(), title="Audit Plan")
    task = create_assignment(db_session, plan.id, date.today(), sub_math.id, TaskType.CUSTOM, 40, title="Accidental Task")
    publish_study_plan(db_session, plan.id)

    # 1. Student completes task
    client.cookies.set(SESSION_COOKIE_NAME, token1)
    resp_comp = client.post(
        f"/student/assignments/{task.id}/complete",
        headers={"X-CSRF-Token": session1.csrf_token},
    )
    assert resp_comp.status_code == 200

    db_session.refresh(task)
    assert task.is_completed is True
    first_completed_at = task.completed_at

    # Check student cannot access tutor reset endpoint
    resp_stu_reset = client.post(
        f"/tutor/assignments/{task.id}/reset-completion",
        headers={"X-CSRF-Token": session1.csrf_token},
    )
    assert resp_stu_reset.status_code == 403

    # Check student cannot access audit records
    resp_stu_audits = client.get(f"/tutor/assignments/{task.id}/audits")
    assert resp_stu_audits.status_code == 403

    # 2. Tutor resets accidental completion
    client.cookies.set(SESSION_COOKIE_NAME, tutor_token)
    resp_reset = client.post(
        f"/tutor/assignments/{task.id}/reset-completion",
        data={"note": "Accidental mark reported by student", "csrf_token": tutor_sess.csrf_token},
        headers={"X-CSRF-Token": tutor_sess.csrf_token},
        follow_redirects=False,
    )
    assert resp_reset.status_code == 303

    db_session.refresh(task)
    assert task.is_completed is False
    assert task.completed_at is None

    # Verify audit entries
    audits = get_assignment_audit_logs(db_session, task.id)
    assert len(audits) == 2
    assert audits[0].action == CompletionAuditAction.RESET
    assert audits[0].performed_by_id == tutor_user.id
    assert audits[1].action == CompletionAuditAction.COMPLETED
    assert audits[1].performed_by_id == st1.id

    # 3. Student re-completes assignment -> records fresh timestamp
    client.cookies.set(SESSION_COOKIE_NAME, token1)
    resp_recomp = client.post(
        f"/student/assignments/{task.id}/complete",
        headers={"X-CSRF-Token": session1.csrf_token},
    )
    assert resp_recomp.status_code == 200

    db_session.refresh(task)
    assert task.is_completed is True
    assert task.completed_at >= first_completed_at
    audits_after = get_assignment_audit_logs(db_session, task.id)
    assert len(audits_after) == 3
    assert audits_after[0].action == CompletionAuditAction.COMPLETED
