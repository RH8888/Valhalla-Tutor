import uuid
from datetime import date, time
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.models.meeting import MeetingType, ProposalStatus
from app.routers.tutor_calendar import (
    get_edit_meeting_modal,
    post_create_meeting,
    post_dismiss_reminder,
    post_edit_meeting,
)
from app.routers.tutor_scheduler import (
    get_proposal_review,
    post_approve_proposal,
    post_regenerate_proposal,
    post_update_proposal_item,
)
from app.services.meeting_service import create_meeting
from app.services.scheduler_service import (
    SchedulerError,
    approve_weekly_proposal,
    generate_weekly_proposal,
    regenerate_unadjusted_items,
    update_proposal_item,
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


def test_shared_modal_container_and_reminder_widget_templates():
    base_html = Path("app/templates/base.html").read_text(encoding="utf-8")
    calendar_html = Path("app/templates/tutor/calendar/calendar.html").read_text(encoding="utf-8")
    student_detail_html = Path("app/templates/tutor/students/detail.html").read_text(encoding="utf-8")
    reminder_html = Path("app/templates/tutor/calendar/partials/reminder_indicator.html").read_text(encoding="utf-8")

    assert 'id="modal-container"' in base_html
    assert 'id="modal-container"' not in calendar_html
    assert 'hx-target="#modal-container"' in student_detail_html
    assert "student-modal-container" not in student_detail_html

    assert 'id="tutor-reminders-widget"' not in reminder_html
    assert 'id="reminders-dropdown-menu"' not in reminder_html
    assert "tutor-reminders-widget" in reminder_html
    assert "reminders-dropdown-menu" in reminder_html
    assert 'hx-target="#modal-container"' in reminder_html
    assert 'hx-target="closest .tutor-reminders-widget"' in reminder_html


def test_scheduler_discarded_proposal_guards_and_invalid_hhmm(
    db_session: Session,
    tutor_user,
):
    st = create_student(
        db_session,
        username="st_sched_guard",
        full_name="Scheduler Guard Student",
        password="Password123!",
        grade="12",
    )

    with pytest.raises(SchedulerError, match="Invalid availability"):
        generate_weekly_proposal(
            db_session,
            tutor=tutor_user,
            target_week_start=date(2026, 6, 6),
            student_selections=[{"student_id": st.id, "duration_minutes": 60, "days": ["saturday"]}],
            avail_start_time_str="25:99",
            avail_end_time_str="21:00",
        )

    proposal = generate_weekly_proposal(
        db_session,
        tutor=tutor_user,
        target_week_start=date(2026, 6, 6),
        student_selections=[{"student_id": st.id, "duration_minutes": 60, "days": ["saturday"]}],
    )
    item = proposal.items[0]

    proposal.status = ProposalStatus.DISCARDED
    db_session.commit()

    with pytest.raises(SchedulerError, match="Only draft"):
        update_proposal_item(
            db_session,
            item_id=item.id,
            scheduled_date=item.scheduled_date,
            start_time_str="15:00",
            duration_minutes=60,
            meeting_type=MeetingType.ONLINE,
            tutor=tutor_user,
        )

    with pytest.raises(SchedulerError, match="Only draft"):
        regenerate_unadjusted_items(db_session, proposal.id, tutor_user)

    with pytest.raises(SchedulerError, match="Only draft"):
        approve_weekly_proposal(db_session, proposal.id, tutor_user)

    resp_update = post_update_proposal_item(
        proposal_id=proposal.id,
        item_id=item.id,
        scheduled_date=item.scheduled_date.isoformat(),
        start_time="15:00",
        duration_minutes=60,
        meeting_type="ONLINE",
        db=db_session,
        current_user=tutor_user,
    )
    assert resp_update.status_code == 303
    assert "?err=" in resp_update.headers["location"]

    resp_regen = post_regenerate_proposal(
        proposal_id=proposal.id,
        db=db_session,
        current_user=tutor_user,
    )
    assert resp_regen.status_code == 303
    assert "?err=" in resp_regen.headers["location"]

    resp_approve = post_approve_proposal(
        proposal_id=proposal.id,
        db=db_session,
        current_user=tutor_user,
    )
    assert resp_approve.status_code == 303
    assert "?err=" in resp_approve.headers["location"]


def test_scheduler_approve_overlap_redirects_cleanly(
    db_session: Session,
    tutor_user,
    tutor_session,
):
    st = create_student(
        db_session,
        username="st_sched_overlap",
        full_name="Overlap Student",
        password="Password123!",
        grade="12",
    )
    proposal = generate_weekly_proposal(
        db_session,
        tutor=tutor_user,
        target_week_start=date(2026, 6, 13),
        student_selections=[{"student_id": st.id, "duration_minutes": 60, "days": ["saturday"]}],
    )
    item = proposal.items[0]
    h, m = map(int, item.start_time_str.split(":"))

    # Create a conflicting meeting at the exact proposed slot
    create_meeting(
        db_session,
        tutor=tutor_user,
        student_id=st.id,
        meeting_date=item.scheduled_date,
        start_time_obj=time(h, m),
        duration_minutes=60,
        meeting_type=MeetingType.ONLINE,
    )

    resp = post_approve_proposal(
        proposal_id=proposal.id,
        db=db_session,
        current_user=tutor_user,
    )
    assert resp.status_code == 303
    assert f"/tutor/scheduler/proposals/{proposal.id}?err=" in resp.headers["location"]

    _, tutor_sess = tutor_session
    review_resp = get_proposal_review(
        proposal_id=proposal.id,
        request=_dummy_request(f"/tutor/scheduler/proposals/{proposal.id}"),
        err="Conflicting meeting",
        db=db_session,
        current_user=tutor_user,
        current_session=tutor_sess,
    )
    assert review_resp.status_code == 200
    assert "Conflicting meeting" in review_resp.body.decode("utf-8")


def test_calendar_routes_handle_missing_meeting_and_bad_reminder_minutes(
    db_session: Session,
    tutor_user,
    tutor_session,
):
    st = create_student(
        db_session,
        username="st_cal_err",
        full_name="Calendar Error Student",
        password="Password123!",
        grade="12",
    )
    _, tutor_sess = tutor_session

    with pytest.raises(HTTPException) as edit_missing_exc:
        get_edit_meeting_modal(
            meeting_id=uuid.uuid4(),
            request=_dummy_request("/tutor/meetings/missing/edit"),
            db=db_session,
            current_user=tutor_user,
            current_session=tutor_sess,
        )
    assert edit_missing_exc.value.status_code == 404

    dismiss_resp = post_dismiss_reminder(
        reminder_id=uuid.uuid4(),
        request=_dummy_request("/tutor/reminders/missing/dismiss"),
        db=db_session,
        current_user=tutor_user,
        current_session=tutor_sess,
    )
    assert dismiss_resp.status_code == 200

    bad_create = post_create_meeting(
        request=_dummy_request("/tutor/meetings"),
        student_id=st.id,
        meeting_date="2026-06-20",
        start_time="15:00",
        duration_minutes=60,
        meeting_type="ONLINE",
        reminder_minutes="not-an-int",
        db=db_session,
        current_user=tutor_user,
        current_session=tutor_sess,
    )
    assert bad_create.status_code == 400
    assert "Reminder minutes" in bad_create.body.decode("utf-8")

    meeting = create_meeting(
        db_session,
        tutor=tutor_user,
        student_id=st.id,
        meeting_date=date(2026, 6, 20),
        start_time_obj=time(15, 0),
        duration_minutes=60,
        meeting_type=MeetingType.ONLINE,
    )
    bad_edit = post_edit_meeting(
        meeting_id=meeting.id,
        request=_dummy_request(f"/tutor/meetings/{meeting.id}/edit"),
        meeting_type="ONLINE",
        reminder_minutes="-5",
        db=db_session,
        current_user=tutor_user,
        current_session=tutor_sess,
    )
    assert bad_edit.status_code == 400
    assert "non-negative" in bad_edit.body.decode("utf-8")
