import uuid
from datetime import date, datetime, time, timedelta
import pytest
from sqlalchemy.orm import Session

from app.core.timezone import now_utc, to_utc
from app.models.meeting import MeetingReminder, MeetingStatus, MeetingType, TutorMeeting
from app.models.user import User, UserRole
from app.services.meeting_service import (
    MeetingNotFoundError,
    MeetingOverlapError,
    MeetingValidationError,
    create_meeting,
    dismiss_reminder,
    get_dashboard_meetings,
    get_due_reminders,
    get_meeting_by_id,
    list_student_meetings,
    list_tutor_meetings,
    reschedule_meeting,
    update_meeting_details,
    update_meeting_status,
)
from app.services.user_service import create_student


def test_create_meeting_success(db_session: Session, tutor_user: User, student_user: User):
    m_date = date.today() + timedelta(days=1)
    m_time = time(14, 0)
    meeting = create_meeting(
        db=db_session,
        tutor=tutor_user,
        student_id=student_user.id,
        meeting_date=m_date,
        start_time_obj=m_time,
        duration_minutes=60,
        meeting_type=MeetingType.ONLINE,
        meeting_url="https://meet.valhalla.local/session1",
        notes="Discuss math algebra",
        reminder_minutes=15,
    )
    assert meeting.id is not None
    assert meeting.status == MeetingStatus.SCHEDULED
    assert meeting.duration_minutes == 60
    assert meeting.meeting_type == MeetingType.ONLINE
    assert meeting.meeting_url == "https://meet.valhalla.local/session1"
    assert len(meeting.reminders) == 1
    assert meeting.reminders[0].scheduled_for == meeting.start_time - timedelta(minutes=15)


def test_create_meeting_invalid_duration(db_session: Session, tutor_user: User, student_user: User):
    with pytest.raises(MeetingValidationError, match="positive"):
        create_meeting(
            db=db_session,
            tutor=tutor_user,
            student_id=student_user.id,
            meeting_date=date.today() + timedelta(days=1),
            start_time_obj=time(10, 0),
            duration_minutes=0,
            meeting_type=MeetingType.ONLINE,
        )


def test_create_meeting_invalid_student(db_session: Session, tutor_user: User):
    with pytest.raises(MeetingValidationError, match="Selected student is not valid"):
        create_meeting(
            db=db_session,
            tutor=tutor_user,
            student_id=uuid.uuid4(),
            meeting_date=date.today() + timedelta(days=1),
            start_time_obj=time(10, 0),
            duration_minutes=45,
            meeting_type=MeetingType.OFFLINE,
            location="Room 101",
        )


def test_meeting_overlap_rejection(db_session: Session, tutor_user: User, student_user: User):
    m_date = date.today() + timedelta(days=2)
    # Create meeting from 10:00 to 11:00
    create_meeting(
        db=db_session,
        tutor=tutor_user,
        student_id=student_user.id,
        meeting_date=m_date,
        start_time_obj=time(10, 0),
        duration_minutes=60,
        meeting_type=MeetingType.ONLINE,
    )

    # 1. Exact overlap (10:00 to 11:00)
    with pytest.raises(MeetingOverlapError):
        create_meeting(
            db=db_session,
            tutor=tutor_user,
            student_id=student_user.id,
            meeting_date=m_date,
            start_time_obj=time(10, 0),
            duration_minutes=60,
            meeting_type=MeetingType.ONLINE,
        )

    # 2. Partial overlap (10:30 to 11:30)
    with pytest.raises(MeetingOverlapError):
        create_meeting(
            db=db_session,
            tutor=tutor_user,
            student_id=student_user.id,
            meeting_date=m_date,
            start_time_obj=time(10, 30),
            duration_minutes=60,
            meeting_type=MeetingType.ONLINE,
        )

    # 3. Non-overlapping immediately following (11:00 to 12:00) - should succeed
    m2 = create_meeting(
        db=db_session,
        tutor=tutor_user,
        student_id=student_user.id,
        meeting_date=m_date,
        start_time_obj=time(11, 0),
        duration_minutes=60,
        meeting_type=MeetingType.ONLINE,
    )
    assert m2.id is not None


def test_reschedule_preserves_history(db_session: Session, tutor_user: User, student_user: User):
    m_date = date.today() + timedelta(days=3)
    meeting = create_meeting(
        db=db_session,
        tutor=tutor_user,
        student_id=student_user.id,
        meeting_date=m_date,
        start_time_obj=time(14, 0),
        duration_minutes=60,
        meeting_type=MeetingType.ONLINE,
        reminder_minutes=30,
    )
    orig_start = meeting.start_time

    # Reschedule to 16:00, 90 mins
    updated = reschedule_meeting(
        db=db_session,
        meeting_id=meeting.id,
        tutor=tutor_user,
        new_date=m_date,
        new_time_obj=time(16, 0),
        new_duration_minutes=90,
        reason="Student requested later hour",
    )
    assert updated.duration_minutes == 90
    assert updated.start_time != orig_start
    assert len(updated.reschedule_history) == 1
    assert updated.reschedule_history[0].previous_duration_minutes == 60
    assert updated.reschedule_history[0].new_duration_minutes == 90
    assert updated.reschedule_history[0].reason == "Student requested later hour"

    # Now the previous slot 14:00 is free!
    reopened = create_meeting(
        db=db_session,
        tutor=tutor_user,
        student_id=student_user.id,
        meeting_date=m_date,
        start_time_obj=time(14, 0),
        duration_minutes=60,
        meeting_type=MeetingType.ONLINE,
    )
    assert reopened.id is not None


def test_meeting_status_and_cancellation(db_session: Session, tutor_user: User, student_user: User):
    m_date = date.today() + timedelta(days=4)
    meeting = create_meeting(
        db=db_session,
        tutor=tutor_user,
        student_id=student_user.id,
        meeting_date=m_date,
        start_time_obj=time(9, 0),
        duration_minutes=45,
        meeting_type=MeetingType.OFFLINE,
        location="Library Room 3",
        reminder_minutes=15,
    )
    assert meeting.status == MeetingStatus.SCHEDULED

    # Mark as student absent
    absent_m = update_meeting_status(db_session, meeting.id, tutor_user, MeetingStatus.STUDENT_ABSENT)
    assert absent_m.status == MeetingStatus.STUDENT_ABSENT

    # Complete meeting
    completed_m = update_meeting_status(db_session, meeting.id, tutor_user, MeetingStatus.COMPLETED)
    assert completed_m.status == MeetingStatus.COMPLETED

    # Cancel meeting
    cancelled_m = update_meeting_status(db_session, meeting.id, tutor_user, MeetingStatus.CANCELLED)
    assert cancelled_m.status == MeetingStatus.CANCELLED

    # Cancelled meeting frees the slot
    replacement = create_meeting(
        db=db_session,
        tutor=tutor_user,
        student_id=student_user.id,
        meeting_date=m_date,
        start_time_obj=time(9, 0),
        duration_minutes=45,
        meeting_type=MeetingType.OFFLINE,
        location="Library Room 3",
    )
    assert replacement.id is not None


def test_in_app_reminders_lifecycle(db_session: Session, tutor_user: User, student_user: User):
    # Create meeting starting in 10 minutes, with 15-minute reminder (meaning reminder is already due!)
    meeting = create_meeting(
        db=db_session,
        tutor=tutor_user,
        student_id=student_user.id,
        meeting_date=date.today(),
        start_time_obj=time(12, 0),
        duration_minutes=30,
        meeting_type=MeetingType.ONLINE,
        reminder_minutes=0,
    )
    # Manually backdate start_time to now
    meeting.start_time = now_utc() - timedelta(minutes=1)
    meeting.end_time = meeting.start_time + timedelta(minutes=30)
    # Sync reminder
    reminder = meeting.reminders[0]
    reminder.scheduled_for = meeting.start_time
    db_session.commit()

    due = get_due_reminders(db_session, tutor_user.id)
    assert len(due) >= 1
    assert any(r.meeting_id == meeting.id for r in due)

    # Dismiss reminder
    target_rem = next(r for r in due if r.meeting_id == meeting.id)
    dismissed = dismiss_reminder(db_session, target_rem.id, tutor_user.id)
    assert dismissed is True

    # After dismissing, it is no longer due
    remaining = get_due_reminders(db_session, tutor_user.id)
    assert not any(r.id == target_rem.id for r in remaining)
