import uuid
from datetime import date, datetime, time, timedelta
import pytest
from sqlalchemy.orm import Session

from app.core.timezone import now_utc
from app.models.meeting import (
    MeetingStatus,
    MeetingType,
    ProposalStatus,
    TutorMeeting,
    WeeklyScheduleProposal,
)
from app.models.message import Message
from app.models.user import User
from app.services.meeting_service import create_meeting, update_meeting_status
from app.services.message_service import get_conversation_by_student_id
from app.services.scheduler_service import (
    approve_weekly_proposal,
    find_available_slot,
    generate_weekly_proposal,
    get_target_week_start,
    learn_student_preferred_hour,
    quick_move_meeting,
    regenerate_unadjusted_items,
    update_proposal_item,
)


def test_learn_preference_insufficient_history(db_session: Session, tutor_user: User, student_user: User):
    # No completed meetings -> returns None (manual selection)
    pref = learn_student_preferred_hour(db_session, student_user.id, tutor_user.timezone)
    assert pref is None

    # Only 1 completed meeting -> still returns None (<2 threshold)
    m1 = create_meeting(
        db=db_session,
        tutor=tutor_user,
        student_id=student_user.id,
        meeting_date=date.today() - timedelta(days=7),
        start_time_obj=time(15, 0),
        duration_minutes=60,
        meeting_type=MeetingType.ONLINE,
    )
    update_meeting_status(db_session, m1.id, tutor_user, MeetingStatus.COMPLETED)

    pref_1 = learn_student_preferred_hour(db_session, student_user.id, tutor_user.timezone)
    assert pref_1 is None


def test_learn_preference_excludes_cancelled_and_absent(db_session: Session, tutor_user: User, student_user: User):
    # Create cancelled and absent meetings at 11:00
    m_canc = create_meeting(
        db=db_session,
        tutor=tutor_user,
        student_id=student_user.id,
        meeting_date=date.today() - timedelta(days=10),
        start_time_obj=time(11, 0),
        duration_minutes=60,
        meeting_type=MeetingType.ONLINE,
    )
    update_meeting_status(db_session, m_canc.id, tutor_user, MeetingStatus.CANCELLED)

    m_abs = create_meeting(
        db=db_session,
        tutor=tutor_user,
        student_id=student_user.id,
        meeting_date=date.today() - timedelta(days=9),
        start_time_obj=time(11, 0),
        duration_minutes=60,
        meeting_type=MeetingType.ONLINE,
    )
    update_meeting_status(db_session, m_abs.id, tutor_user, MeetingStatus.STUDENT_ABSENT)

    # Cancelled / absent do not count as completed history
    assert learn_student_preferred_hour(db_session, student_user.id, tutor_user.timezone) is None


def test_learn_preference_with_recency_weighting(db_session: Session, tutor_user: User, student_user: User):
    # Older completed meetings at 14:00 (3 weeks ago and 2 weeks ago)
    m1 = create_meeting(
        db=db_session,
        tutor=tutor_user,
        student_id=student_user.id,
        meeting_date=date.today() - timedelta(days=21),
        start_time_obj=time(14, 0),
        duration_minutes=60,
        meeting_type=MeetingType.ONLINE,
    )
    update_meeting_status(db_session, m1.id, tutor_user, MeetingStatus.COMPLETED)

    m2 = create_meeting(
        db=db_session,
        tutor=tutor_user,
        student_id=student_user.id,
        meeting_date=date.today() - timedelta(days=14),
        start_time_obj=time(14, 0),
        duration_minutes=60,
        meeting_type=MeetingType.ONLINE,
    )
    update_meeting_status(db_session, m2.id, tutor_user, MeetingStatus.COMPLETED)

    # Recent meetings at 17:00 (7 days ago and 2 days ago)
    m3 = create_meeting(
        db=db_session,
        tutor=tutor_user,
        student_id=student_user.id,
        meeting_date=date.today() - timedelta(days=7),
        start_time_obj=time(17, 0),
        duration_minutes=60,
        meeting_type=MeetingType.ONLINE,
    )
    update_meeting_status(db_session, m3.id, tutor_user, MeetingStatus.COMPLETED)

    m4 = create_meeting(
        db=db_session,
        tutor=tutor_user,
        student_id=student_user.id,
        meeting_date=date.today() - timedelta(days=2),
        start_time_obj=time(17, 0),
        duration_minutes=60,
        meeting_type=MeetingType.ONLINE,
    )
    update_meeting_status(db_session, m4.id, tutor_user, MeetingStatus.COMPLETED)

    pref = learn_student_preferred_hour(db_session, student_user.id, tutor_user.timezone)
    assert pref is not None
    time_str, explanation = pref
    assert time_str == "17:00"
    assert "Learned from 4 completed sessions" in explanation


def test_target_week_calculation_friday_and_thursday():
    # Thursday (e.g. 2026-11-19) -> Saturday of this week is 2026-11-21
    thursday = date(2026, 11, 19)
    assert thursday.weekday() == 3
    sat_target_thurs = get_target_week_start(thursday)
    assert sat_target_thurs == date(2026, 11, 21)

    # Friday (e.g. 2026-11-20) -> Saturday starting upcoming week is 2026-11-21
    friday = date(2026, 11, 20)
    assert friday.weekday() == 4
    sat_target_fri = get_target_week_start(friday)
    assert sat_target_fri == date(2026, 11, 21)


def test_proposal_lifecycle_approval_and_private_notifications(
    db_session: Session,
    tutor_user: User,
    student_user: User,
):
    target_sat = date(2026, 12, 5)  # Saturday
    selections = [
        {
            "student_id": student_user.id,
            "days": ["saturday", "monday"],
            "duration_minutes": 60,
            "meeting_type": MeetingType.ONLINE,
            "meeting_url": "https://meet.google.com/test-room",
        }
    ]

    proposal = generate_weekly_proposal(
        db=db_session,
        tutor=tutor_user,
        target_week_start=target_sat,
        student_selections=selections,
    )
    assert proposal.id is not None
    assert proposal.status == ProposalStatus.DRAFT
    assert len(proposal.items) == 2

    # Manually adjust item 1
    item1 = proposal.items[0]
    update_proposal_item(
        db=db_session,
        item_id=item1.id,
        scheduled_date=item1.scheduled_date,
        start_time_str="18:30",
        duration_minutes=45,
        meeting_type=MeetingType.ONLINE,
        notes="Student requested 18:30",
    )
    assert item1.is_manually_adjusted is True
    assert item1.start_time_str == "18:30"

    # Regenerate unadjusted items: manually adjusted item remains 18:30
    regenerate_unadjusted_items(db_session, proposal.id, tutor_user)
    assert item1.start_time_str == "18:30"

    # Approve proposal
    meetings = approve_weekly_proposal(db_session, proposal.id, tutor_user)
    assert len(meetings) == 2
    assert proposal.status == ProposalStatus.APPROVED
    assert all(m.notification_sent_at is not None for m in meetings)

    # Verify student received private in-app notification messages
    conv = get_conversation_by_student_id(db_session, student_user.id)
    assert conv is not None
    assert len(conv.messages) >= 2
    assert any("Weekly Session Scheduled" in m.content for m in conv.messages)

    # Calling approve again is idempotent (no duplicate meetings or messages)
    initial_msg_count = len(conv.messages)
    approve_again = approve_weekly_proposal(db_session, proposal.id, tutor_user)
    assert len(approve_again) == 2
    assert len(conv.messages) == initial_msg_count


def test_quick_move_meeting_and_notification(
    db_session: Session,
    tutor_user: User,
    student_user: User,
):
    m_date = date.today() + timedelta(days=5)
    meeting = create_meeting(
        db=db_session,
        tutor=tutor_user,
        student_id=student_user.id,
        meeting_date=m_date,
        start_time_obj=time(14, 0),
        duration_minutes=60,
        meeting_type=MeetingType.ONLINE,
    )

    # Quick move to 16:00
    moved = quick_move_meeting(
        db=db_session,
        meeting_id=meeting.id,
        tutor=tutor_user,
        target_date=m_date,
        target_time_str="16:00",
        notify_student=True,
    )
    assert moved.duration_minutes == 60
    assert len(moved.reschedule_history) == 1
    assert moved.notification_sent_at is not None

    conv = get_conversation_by_student_id(db_session, student_user.id)
    assert conv is not None
    assert any("Session Rescheduled" in m.content for m in conv.messages)


def test_proposal_strictly_respects_tutor_availability_window(
    db_session: Session,
    tutor_user: User,
    student_user: User,
):
    target_sat = date(2026, 12, 12)
    # Tutor is only available from 15:00 to 18:00
    proposal = generate_weekly_proposal(
        db=db_session,
        tutor=tutor_user,
        target_week_start=target_sat,
        student_selections=[
            {
                "student_id": student_user.id,
                "days": ["saturday", "sunday"],
                "duration_minutes": 60,
                "meeting_type": MeetingType.ONLINE,
            }
        ],
        avail_start_time_str="15:00",
        avail_end_time_str="18:00",
    )
    assert proposal.avail_start_time_str == "15:00"
    assert proposal.avail_end_time_str == "18:00"

    for item in proposal.items:
        h, m = map(int, item.start_time_str.split(":"))
        start_min = h * 60 + m
        end_min = start_min + item.duration_minutes
        # 15:00 is 900 minutes, 18:00 is 1080 minutes
        assert start_min >= 15 * 60, f"Proposed start {item.start_time_str} is earlier than available 15:00"
        assert end_min <= 18 * 60, f"Proposed end {end_min} exceeds available 18:00"
