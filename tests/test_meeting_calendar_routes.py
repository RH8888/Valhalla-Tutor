import uuid
from datetime import date, datetime, time, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.dependencies import SESSION_COOKIE_NAME
from app.core.timezone import now_utc
from app.models.meeting import MeetingStatus, MeetingType, TutorMeeting
from app.models.user import User, UserRole
from app.services.auth_service import create_session
from app.services.meeting_service import create_meeting
from app.services.tutor_provision import provision_tutor


def test_unauthenticated_calendar_access(client: TestClient):
    response = client.get("/tutor/calendar", follow_redirects=False)
    assert response.status_code in (401, 303)


def test_student_forbidden_from_tutor_calendar(
    client: TestClient,
    student_session: tuple,
):
    token, _ = student_session
    client.cookies.set(SESSION_COOKIE_NAME, token)
    response = client.get("/tutor/calendar", follow_redirects=False)
    # Student role accessing require_tutor raises 403 or redirects
    assert response.status_code in (403, 303)


def test_tutor_can_access_calendar_views(
    client: TestClient,
    tutor_session: tuple,
):
    token, _ = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, token)

    # Month view
    resp_month = client.get("/tutor/calendar?view=month")
    assert resp_month.status_code == 200
    assert "Calendar" in resp_month.text
    assert "Month" in resp_month.text

    # Week view
    resp_week = client.get("/tutor/calendar?view=week")
    assert resp_week.status_code == 200
    assert "Week" in resp_week.text

    # Day view
    resp_day = client.get("/tutor/calendar?view=day")
    assert resp_day.status_code == 200
    assert "Day" in resp_day.text


def test_tutor_create_meeting_flow_and_overlap(
    client: TestClient,
    tutor_session: tuple,
    student_user: User,
):
    token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, token)
    headers = {"X-CSRF-Token": session_rec.csrf_token}

    # Open modal
    modal_resp = client.get(f"/tutor/meetings/new?student_id={student_user.id}")
    assert modal_resp.status_code == 200
    assert "Schedule New Meeting" in modal_resp.text

    m_date = (date.today() + timedelta(days=2)).strftime("%Y-%m-%d")
    # Post meeting create
    create_resp = client.post(
        "/tutor/meetings",
        data={
            "student_id": str(student_user.id),
            "meeting_date": m_date,
            "start_time": "15:00",
            "duration_minutes": 60,
            "meeting_type": "ONLINE",
            "meeting_url": "https://meet.google.com/abc-defg-hij",
            "notes": "Discuss quadratic formulas",
            "reminder_minutes": "15",
            "csrf_token": session_rec.csrf_token,
        },
        headers=headers,
    )
    assert create_resp.status_code == 200
    assert "meetingChanged" in create_resp.headers.get("HX-Trigger", "")

    # Overlapping meeting at 15:30 should fail with 400
    overlap_resp = client.post(
        "/tutor/meetings",
        data={
            "student_id": str(student_user.id),
            "meeting_date": m_date,
            "start_time": "15:30",
            "duration_minutes": 45,
            "meeting_type": "ONLINE",
            "reminder_minutes": "none",
            "csrf_token": session_rec.csrf_token,
        },
        headers=headers,
    )
    assert overlap_resp.status_code == 400
    assert "overlaps" in overlap_resp.text.lower()


def test_meeting_reschedule_status_and_reminders(
    client: TestClient,
    tutor_session: tuple,
    tutor_user: User,
    student_user: User,
    db_session: Session,
):
    token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, token)
    headers = {"X-CSRF-Token": session_rec.csrf_token}

    m_date = date.today() + timedelta(days=5)
    meeting = create_meeting(
        db=db_session,
        tutor=tutor_user,
        student_id=student_user.id,
        meeting_date=m_date,
        start_time_obj=time(10, 0),
        duration_minutes=60,
        meeting_type=MeetingType.ONLINE,
        reminder_minutes=0,
    )

    # 1. Reschedule meeting
    resched_resp = client.post(
        f"/tutor/meetings/{meeting.id}/reschedule",
        data={
            "new_date": m_date.strftime("%Y-%m-%d"),
            "new_time": "11:30",
            "new_duration_minutes": 45,
            "reason": "Doctor appointment",
            "csrf_token": session_rec.csrf_token,
        },
        headers=headers,
    )
    assert resched_resp.status_code == 200
    assert "meetingChanged" in resched_resp.headers.get("HX-Trigger", "")

    # Verify meeting detail modal shows history
    detail_resp = client.get(f"/tutor/meetings/{meeting.id}")
    assert detail_resp.status_code == 200
    assert "Rescheduling History" in detail_resp.text
    assert "Doctor appointment" in detail_resp.text

    # 2. Transition status to COMPLETED
    status_resp = client.post(
        f"/tutor/meetings/{meeting.id}/status",
        data={
            "new_status": "COMPLETED",
            "csrf_token": session_rec.csrf_token,
        },
        headers=headers,
    )
    assert status_resp.status_code == 200

    # 3. Check reminders endpoint
    rem_resp = client.get("/tutor/reminders/unread")
    assert rem_resp.status_code == 200
    assert "tutor-reminders-widget" in rem_resp.text


def test_cross_tutor_meeting_isolation(
    client: TestClient,
    tutor_session: tuple,
    student_user: User,
    db_session: Session,
):
    token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, token)

    # Create distinct second tutor
    from app.core.security import hash_password
    other_tutor = User(
        username="other_tutor",
        hashed_password=hash_password("OtherTutorSecret123!"),
        role=UserRole.TUTOR,
        full_name="Other Tutor",
        timezone="Asia/Tehran",
    )
    db_session.add(other_tutor)
    db_session.commit()
    other_meeting = create_meeting(
        db=db_session,
        tutor=other_tutor,
        student_id=student_user.id,
        meeting_date=date.today() + timedelta(days=6),
        start_time_obj=time(14, 0),
        duration_minutes=60,
        meeting_type=MeetingType.OFFLINE,
        location="Room 202",
    )

    # Tutor 1 attempting to view other tutor's meeting should get 404
    resp = client.get(f"/tutor/meetings/{other_meeting.id}")
    assert resp.status_code == 404
