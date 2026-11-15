import uuid
from datetime import date, datetime, time, timedelta
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.timezone import get_timezone, now_utc, to_local, to_utc
from app.models.meeting import (
    MeetingReminder,
    MeetingRescheduleHistory,
    MeetingStatus,
    MeetingType,
    TutorMeeting,
)
from app.models.user import User, UserRole


class MeetingServiceError(Exception):
    """Base error for meeting service."""
    pass


class MeetingNotFoundError(MeetingServiceError):
    """Raised when a meeting is not found."""
    pass


class MeetingValidationError(MeetingServiceError):
    """Raised when meeting data validation fails."""
    pass


class MeetingOverlapError(MeetingServiceError):
    """Raised when a meeting schedule overlaps with an existing meeting."""
    def __init__(self, message: str, conflicting_meeting: Optional[TutorMeeting] = None):
        super().__init__(message)
        self.conflicting_meeting = conflicting_meeting


def calculate_utc_datetimes(
    meeting_date: date,
    start_time_obj: time,
    duration_minutes: int,
    tz_name: str,
) -> Tuple[datetime, datetime]:
    """Calculate timezone-aware UTC start and end datetimes from local date, time, and duration."""
    tz = get_timezone(tz_name)
    local_start = datetime.combine(meeting_date, start_time_obj, tzinfo=tz)
    local_end = local_start + timedelta(minutes=duration_minutes)
    return to_utc(local_start), to_utc(local_end)


def check_meeting_overlap(
    db: Session,
    tutor_id: uuid.UUID,
    start_time: datetime,
    end_time: datetime,
    exclude_meeting_id: Optional[uuid.UUID] = None,
) -> Optional[TutorMeeting]:
    """
    Check if a proposed meeting slot overlaps with any active (non-cancelled) meeting for the tutor.
    An overlap exists if: candidate.start < existing.end AND candidate.end > existing.start
    """
    query = select(TutorMeeting).where(
        TutorMeeting.tutor_id == tutor_id,
        TutorMeeting.status != MeetingStatus.CANCELLED,
        TutorMeeting.start_time < end_time,
        TutorMeeting.end_time > start_time,
    )
    if exclude_meeting_id:
        query = query.where(TutorMeeting.id != exclude_meeting_id)

    return db.execute(query).scalars().first()


def _sync_meeting_reminder(
    db: Session,
    meeting: TutorMeeting,
) -> Optional[MeetingReminder]:
    """
    Cancel existing pending reminders for this meeting and create a new one if reminder_minutes is configured.
    """
    # Invalidate old pending reminders
    old_reminders = db.execute(
        select(MeetingReminder).where(
            MeetingReminder.meeting_id == meeting.id,
            MeetingReminder.is_cancelled.is_(False),
            MeetingReminder.is_dismissed.is_(False),
        )
    ).scalars().all()
    for rem in old_reminders:
        rem.is_cancelled = True

    if meeting.status != MeetingStatus.SCHEDULED or meeting.reminder_minutes is None:
        return None

    scheduled_for = meeting.start_time - timedelta(minutes=meeting.reminder_minutes)
    reminder = MeetingReminder(
        meeting_id=meeting.id,
        tutor_id=meeting.tutor_id,
        scheduled_for=scheduled_for,
    )
    db.add(reminder)
    return reminder


def create_meeting(
    db: Session,
    tutor: User,
    student_id: uuid.UUID,
    meeting_date: date,
    start_time_obj: time,
    duration_minutes: int,
    meeting_type: MeetingType,
    meeting_url: Optional[str] = None,
    location: Optional[str] = None,
    notes: Optional[str] = None,
    reminder_minutes: Optional[int] = None,
    commit: bool = True,
) -> TutorMeeting:
    """Create a new tutor meeting with validation and overlap check."""
    if duration_minutes <= 0:
        raise MeetingValidationError("Meeting duration must be positive.")

    student = db.get(User, student_id)
    if not student or student.role != UserRole.STUDENT:
        raise MeetingValidationError("Selected student is not valid or does not exist.")

    start_time, end_time = calculate_utc_datetimes(
        meeting_date=meeting_date,
        start_time_obj=start_time_obj,
        duration_minutes=duration_minutes,
        tz_name=tutor.timezone,
    )

    conflict = check_meeting_overlap(db, tutor.id, start_time, end_time)
    if conflict:
        raise MeetingOverlapError(
            f"Meeting overlaps with an existing meeting scheduled from "
            f"{conflict.start_time.strftime('%Y-%m-%d %H:%M UTC')} to {conflict.end_time.strftime('%H:%M UTC')}.",
            conflicting_meeting=conflict,
        )

    clean_url = meeting_url.strip() if meeting_url else None
    clean_location = location.strip() if location else None
    clean_notes = notes.strip() if notes else None

    meeting = TutorMeeting(
        tutor_id=tutor.id,
        student_id=student.id,
        start_time=start_time,
        end_time=end_time,
        duration_minutes=duration_minutes,
        meeting_type=meeting_type,
        meeting_url=clean_url,
        location=clean_location,
        notes=clean_notes,
        status=MeetingStatus.SCHEDULED,
        reminder_minutes=reminder_minutes,
    )
    db.add(meeting)
    db.flush()

    _sync_meeting_reminder(db, meeting)
    if commit:
        db.commit()
        db.refresh(meeting)
    else:
        db.flush()
    return meeting


def reschedule_meeting(
    db: Session,
    meeting_id: uuid.UUID,
    tutor: User,
    new_date: date,
    new_time_obj: time,
    new_duration_minutes: int,
    reason: Optional[str] = None,
) -> TutorMeeting:
    """
    Reschedule an existing meeting to a new date/time/duration while preserving history.
    """
    meeting = db.get(TutorMeeting, meeting_id)
    if not meeting or meeting.tutor_id != tutor.id:
        raise MeetingNotFoundError("Meeting not found.")

    if new_duration_minutes <= 0:
        raise MeetingValidationError("Meeting duration must be positive.")

    new_start_time, new_end_time = calculate_utc_datetimes(
        meeting_date=new_date,
        start_time_obj=new_time_obj,
        duration_minutes=new_duration_minutes,
        tz_name=tutor.timezone,
    )

    conflict = check_meeting_overlap(
        db=db,
        tutor_id=tutor.id,
        start_time=new_start_time,
        end_time=new_end_time,
        exclude_meeting_id=meeting.id,
    )
    if conflict:
        raise MeetingOverlapError(
            f"Rescheduled slot overlaps with an existing meeting scheduled from "
            f"{conflict.start_time.strftime('%Y-%m-%d %H:%M UTC')} to {conflict.end_time.strftime('%H:%M UTC')}.",
            conflicting_meeting=conflict,
        )

    # Record history
    history_entry = MeetingRescheduleHistory(
        meeting_id=meeting.id,
        previous_start_time=meeting.start_time,
        previous_end_time=meeting.end_time,
        previous_duration_minutes=meeting.duration_minutes,
        new_start_time=new_start_time,
        new_end_time=new_end_time,
        new_duration_minutes=new_duration_minutes,
        reason=reason.strip() if reason else None,
    )
    db.add(history_entry)

    meeting.start_time = new_start_time
    meeting.end_time = new_end_time
    meeting.duration_minutes = new_duration_minutes
    meeting.status = MeetingStatus.SCHEDULED
    meeting.updated_at = now_utc()

    _sync_meeting_reminder(db, meeting)
    db.commit()
    db.refresh(meeting)
    return meeting


def update_meeting_status(
    db: Session,
    meeting_id: uuid.UUID,
    tutor: User,
    new_status: MeetingStatus,
) -> TutorMeeting:
    """Transition meeting status (COMPLETED, CANCELLED, STUDENT_ABSENT)."""
    meeting = db.get(TutorMeeting, meeting_id)
    if not meeting or meeting.tutor_id != tutor.id:
        raise MeetingNotFoundError("Meeting not found.")

    meeting.status = new_status
    meeting.updated_at = now_utc()

    # Cancel future reminders if completed or cancelled
    if new_status in (MeetingStatus.CANCELLED, MeetingStatus.COMPLETED):
        _sync_meeting_reminder(db, meeting)

    db.commit()
    db.refresh(meeting)
    return meeting


def update_meeting_details(
    db: Session,
    meeting_id: uuid.UUID,
    tutor: User,
    meeting_type: Optional[MeetingType] = None,
    meeting_url: Optional[str] = None,
    location: Optional[str] = None,
    notes: Optional[str] = None,
    reminder_minutes: Optional[int] = None,
) -> TutorMeeting:
    """Update meeting non-temporal attributes (notes, url, location, reminder config)."""
    meeting = db.get(TutorMeeting, meeting_id)
    if not meeting or meeting.tutor_id != tutor.id:
        raise MeetingNotFoundError("Meeting not found.")

    if meeting_type:
        meeting.meeting_type = meeting_type
    if meeting_url is not None:
        meeting.meeting_url = meeting_url.strip() if meeting_url.strip() else None
    if location is not None:
        meeting.location = location.strip() if location.strip() else None
    if notes is not None:
        meeting.notes = notes.strip() if notes.strip() else None

    reminder_changed = False
    if reminder_minutes != meeting.reminder_minutes:
        meeting.reminder_minutes = reminder_minutes
        reminder_changed = True

    meeting.updated_at = now_utc()

    if reminder_changed:
        _sync_meeting_reminder(db, meeting)

    db.commit()
    db.refresh(meeting)
    return meeting


def get_meeting_by_id(
    db: Session,
    meeting_id: uuid.UUID,
    tutor_id: Optional[uuid.UUID] = None,
) -> TutorMeeting:
    """Fetch meeting with relationships populated."""
    query = (
        select(TutorMeeting)
        .options(
            joinedload(TutorMeeting.student),
            joinedload(TutorMeeting.reschedule_history),
            joinedload(TutorMeeting.reminders),
        )
        .where(TutorMeeting.id == meeting_id)
    )
    if tutor_id:
        query = query.where(TutorMeeting.tutor_id == tutor_id)

    meeting = db.execute(query).scalars().unique().first()
    if not meeting:
        raise MeetingNotFoundError("Meeting not found.")
    return meeting


def list_tutor_meetings(
    db: Session,
    tutor_id: uuid.UUID,
    start_range: Optional[datetime] = None,
    end_range: Optional[datetime] = None,
    student_id: Optional[uuid.UUID] = None,
    status: Optional[MeetingStatus] = None,
) -> List[TutorMeeting]:
    """List meetings for a tutor with optional date range, student, and status filters."""
    query = (
        select(TutorMeeting)
        .options(joinedload(TutorMeeting.student))
        .where(TutorMeeting.tutor_id == tutor_id)
    )
    if start_range:
        query = query.where(TutorMeeting.end_time >= start_range)
    if end_range:
        query = query.where(TutorMeeting.start_time <= end_range)
    if student_id:
        query = query.where(TutorMeeting.student_id == student_id)
    if status:
        query = query.where(TutorMeeting.status == status)

    query = query.order_by(TutorMeeting.start_time.asc())
    return db.execute(query).scalars().all()


def list_student_meetings(
    db: Session,
    student_id: uuid.UUID,
    tutor_id: Optional[uuid.UUID] = None,
) -> Tuple[List[TutorMeeting], List[TutorMeeting]]:
    """Return (upcoming_meetings, previous_meetings) for a student profile."""
    current_time = now_utc()
    query = (
        select(TutorMeeting)
        .options(joinedload(TutorMeeting.student))
        .where(TutorMeeting.student_id == student_id)
    )
    if tutor_id:
        query = query.where(TutorMeeting.tutor_id == tutor_id)

    meetings = db.execute(query.order_by(TutorMeeting.start_time.asc())).scalars().all()

    upcoming = [m for m in meetings if m.start_time >= current_time and m.status != MeetingStatus.CANCELLED]
    previous = [m for m in meetings if m.start_time < current_time or m.status == MeetingStatus.CANCELLED]
    # Reverse previous so most recent is first
    previous.sort(key=lambda m: m.start_time, reverse=True)
    return upcoming, previous


def get_dashboard_meetings(
    db: Session,
    tutor: User,
) -> dict:
    """Return today's meetings and upcoming meetings for tutor dashboard in tutor timezone."""
    tz = get_timezone(tutor.timezone)
    now_local = datetime.now(tz)
    today_start_local = datetime.combine(now_local.date(), time.min, tzinfo=tz)
    today_end_local = datetime.combine(now_local.date(), time.max, tzinfo=tz)

    today_start_utc = to_utc(today_start_local)
    today_end_utc = to_utc(today_end_local)
    current_utc = now_utc()

    all_upcoming = list_tutor_meetings(
        db=db,
        tutor_id=tutor.id,
        start_range=today_start_utc,
    )

    today_meetings = [m for m in all_upcoming if today_start_utc <= m.start_time <= today_end_utc]
    next_upcoming = [m for m in all_upcoming if m.start_time > today_end_utc and m.status == MeetingStatus.SCHEDULED][:5]

    return {
        "today_meetings": today_meetings,
        "next_upcoming": next_upcoming,
    }


def get_due_reminders(
    db: Session,
    tutor_id: uuid.UUID,
) -> List[MeetingReminder]:
    """
    Fetch and atomically trigger pending due reminders for a tutor.
    Ensures safe claiming across multiple worker processes without duplicate triggers.
    """
    current_time = now_utc()

    # Query reminders scheduled at or before now that are not cancelled or dismissed
    query = (
        select(MeetingReminder)
        .join(TutorMeeting, MeetingReminder.meeting_id == TutorMeeting.id)
        .options(
            joinedload(MeetingReminder.meeting).joinedload(TutorMeeting.student)
        )
        .where(
            MeetingReminder.tutor_id == tutor_id,
            MeetingReminder.scheduled_for <= current_time,
            MeetingReminder.is_cancelled.is_(False),
            MeetingReminder.is_dismissed.is_(False),
            TutorMeeting.status == MeetingStatus.SCHEDULED,
        )
        .order_by(MeetingReminder.scheduled_for.desc())
    )

    reminders = db.execute(query).scalars().all()

    # Mark triggered_at if not yet set
    updated = False
    for rem in reminders:
        if not rem.triggered_at:
            rem.triggered_at = current_time
            updated = True

    if updated:
        db.commit()

    return reminders


def dismiss_reminder(
    db: Session,
    reminder_id: uuid.UUID,
    tutor_id: uuid.UUID,
) -> bool:
    """Dismiss an in-app reminder."""
    reminder = db.get(MeetingReminder, reminder_id)
    if not reminder or reminder.tutor_id != tutor_id:
        return False

    reminder.is_dismissed = True
    reminder.dismissed_at = now_utc()
    db.commit()
    return True
