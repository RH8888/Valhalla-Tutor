import uuid
from datetime import date, datetime, time, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.dependencies import SESSION_COOKIE_NAME
from app.models.meeting import MeetingStatus, MeetingType, ProposalStatus
from app.models.user import User
from app.services.meeting_service import create_meeting
from app.services.message_service import get_conversation_by_student_id


def test_student_forbidden_from_scheduler(
    client: TestClient,
    student_session: tuple,
):
    token, _ = student_session
    client.cookies.set(SESSION_COOKIE_NAME, token)
    response = client.get("/tutor/scheduler", follow_redirects=False)
    assert response.status_code in (401, 403, 303)


def test_tutor_access_scheduler_dashboard(
    client: TestClient,
    tutor_session: tuple,
    student_user: User,
):
    token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, token)

    response = client.get("/tutor/scheduler")
    assert response.status_code == 200
    assert "Semi-Automatic Weekly Scheduler" in response.text
    assert student_user.full_name in response.text


def test_generate_and_approve_proposal_flow(
    client: TestClient,
    tutor_session: tuple,
    student_user: User,
    db_session: Session,
):
    token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, token)
    headers = {"X-CSRF-Token": session_rec.csrf_token}

    # 1. Generate schedule proposal
    gen_resp = client.post(
        "/tutor/scheduler/generate",
        data={
            "target_week_start": "2026-12-12",
            "selected_students": [str(student_user.id)],
            f"days_{student_user.id}": ["saturday", "tuesday"],
            f"duration_{student_user.id}": "60",
            f"type_{student_user.id}": "ONLINE",
            f"url_{student_user.id}": "https://meet.valhalla.local/sched",
            "csrf_token": session_rec.csrf_token,
        },
        headers=headers,
        follow_redirects=True,
    )
    assert gen_resp.status_code == 200
    assert "Review Proposed Weekly Schedule" in gen_resp.text
    assert student_user.full_name in gen_resp.text

    # Extract proposal id from final url
    url_path = gen_resp.history[-1].headers["location"] if gen_resp.history else gen_resp.request.url.path
    proposal_id = url_path.split("/")[-1]

    # 2. Approve proposal
    appr_resp = client.post(
        f"/tutor/scheduler/proposals/{proposal_id}/approve",
        data={"csrf_token": session_rec.csrf_token},
        headers=headers,
        follow_redirects=True,
    )
    assert appr_resp.status_code == 200
    assert "Calendar" in appr_resp.text

    # Verify student received in-app chat message
    conv = get_conversation_by_student_id(db_session, student_user.id)
    assert conv is not None
    assert any("Weekly Session Scheduled" in m.content for m in conv.messages)


def test_quick_move_route_and_student_notice(
    client: TestClient,
    tutor_session: tuple,
    tutor_user: User,
    student_user: User,
    db_session: Session,
):
    token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, token)
    headers = {"X-CSRF-Token": session_rec.csrf_token}

    m_date = date.today() + timedelta(days=7)
    meeting = create_meeting(
        db=db_session,
        tutor=tutor_user,
        student_id=student_user.id,
        meeting_date=m_date,
        start_time_obj=time(14, 0),
        duration_minutes=60,
        meeting_type=MeetingType.ONLINE,
    )

    move_resp = client.post(
        f"/tutor/meetings/{meeting.id}/quick-move",
        data={
            "target_date": m_date.strftime("%Y-%m-%d"),
            "target_time": "18:00",
            "notify": "true",
            "csrf_token": session_rec.csrf_token,
        },
        headers=headers,
    )
    assert move_resp.status_code in (200, 303)

    conv = get_conversation_by_student_id(db_session, student_user.id)
    assert conv is not None
    assert any("Session Rescheduled" in m.content for m in conv.messages)
