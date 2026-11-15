import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy import and_, select
from sqlalchemy.orm import Session, joinedload

from app.core.timezone import get_timezone, now_utc, to_local, to_utc
from app.models.meeting import (
    MeetingStatus,
    MeetingType,
    ProposalStatus,
    TutorMeeting,
    WeeklyScheduleItem,
    WeeklyScheduleProposal,
)
from app.models.user import User, UserRole
from app.services.meeting_service import (
    MeetingOverlapError,
    MeetingValidationError,
    calculate_utc_datetimes,
    check_meeting_overlap,
    create_meeting,
    reschedule_meeting,
)
from app.services.message_service import get_or_create_conversation, send_message


class SchedulerError(Exception):
    pass


def learn_student_preferred_hour(
    db: Session,
    student_id: uuid.UUID,
    tz_name: str = "Asia/Tehran",
) -> Optional[Tuple[str, str]]:
    """
    Learn preferred meeting hour based on COMPLETED meetings only.
    - Cancelled and absent meetings are ignored.
    - More recent meetings are weighted higher using exponential decay: w = 1 / (1 + weeks_ago).
    - Requires at least 2 completed sessions; otherwise returns None (first two weeks manual).
    """
    query = (
        select(TutorMeeting)
        .where(
            TutorMeeting.student_id == student_id,
            TutorMeeting.status == MeetingStatus.COMPLETED,
        )
        .order_by(TutorMeeting.start_time.desc())
    )
    completed_meetings = db.execute(query).scalars().all()

    if len(completed_meetings) < 2:
        return None

    current_time = now_utc()
    hour_weights: Dict[int, float] = defaultdict(float)

    for m in completed_meetings:
        local_time = to_local(m.start_time, tz_name)
        h = local_time.hour
        m_start_utc = to_utc(m.start_time)
        age_days = max(0, (current_time - m_start_utc).days)
        weeks_ago = age_days / 7.0
        weight = 1.0 / (1.0 + weeks_ago)
        hour_weights[h] += weight

    best_hour = max(hour_weights.keys(), key=lambda h: hour_weights[h])
    time_str = f"{best_hour:02d}:00"
    explanation = f"Learned from {len(completed_meetings)} completed sessions (preferred: {time_str})"
    return time_str, explanation


def get_target_week_start(
    reference_date: Optional[date] = None,
    tz_name: str = "Asia/Tehran",
) -> date:
    """
    Calculate the upcoming Saturday starting the target week:
    - In Tehran calendar, weeks start on Saturday (weekday 5 in Python: Mon=0, Sun=6).
    - Every Friday (weekday 4): prepare for following week (tomorrow's Saturday).
    - Saturday meetings must be prepared on Thursday (weekday 3) instead.
    """
    if not reference_date:
        tz = get_timezone(tz_name)
        reference_date = datetime.now(tz).date()

    weekday = reference_date.weekday()
    # Days until Saturday (weekday 5)
    days_to_sat = (5 - weekday) % 7
    if days_to_sat == 0:
        # If today is Saturday, target the upcoming Saturday next week
        return reference_date + timedelta(days=7)
    return reference_date + timedelta(days=days_to_sat)


def find_available_slot(
    db: Session,
    tutor_id: uuid.UUID,
    target_date: date,
    preferred_time_obj: time,
    duration_minutes: int,
    tz_name: str,
    booked_slots: List[Tuple[datetime, datetime]],
) -> Optional[time]:
    """
    Find conflict-free time slot in tutor's working window (09:00 - 21:00).
    Starts with preferred time, then branches out by nearest hour distance.
    """
    start_h = preferred_time_obj.hour
    candidate_hours = sorted(range(9, 21), key=lambda h: abs(h - start_h))

    for h in candidate_hours:
        candidate_time = time(h, preferred_time_obj.minute)
        utc_start, utc_end = calculate_utc_datetimes(target_date, candidate_time, duration_minutes, tz_name)

        # Check existing database meetings
        db_conflict = check_meeting_overlap(db, tutor_id, utc_start, utc_end)
        if db_conflict:
            continue

        # Check in-memory booked slots for this proposal
        slot_conflict = any(utc_start < b_end and utc_end > b_start for b_start, b_end in booked_slots)
        if slot_conflict:
            continue

        return candidate_time

    return None

DAY_OFFSETS = {
    "saturday": 0,
    "sunday": 1,
    "monday": 2,
    "tuesday": 3,
    "wednesday": 4,
    "thursday": 5,
    "friday": 6,
}


def generate_weekly_proposal(
    db: Session,
    tutor: User,
    target_week_start: date,
    student_selections: List[dict],
) -> WeeklyScheduleProposal:
    """
    Generate a semi-automatic weekly schedule proposal in DRAFT state.
    student_selections format: [
        {
            "student_id": uuid.UUID,
            "days": ["saturday", "tuesday"],
            "duration_minutes": 60,
            "meeting_type": MeetingType.ONLINE,
            "meeting_url": Optional[str],
            "location": Optional[str],
        }
    ]
    """
    proposal = WeeklyScheduleProposal(
        tutor_id=tutor.id,
        target_week_start=target_week_start,
        status=ProposalStatus.DRAFT,
    )
    db.add(proposal)
    db.flush()

    booked_slots: List[Tuple[datetime, datetime]] = []

    for item in student_selections:
        s_id = item["student_id"]
        dur = item.get("duration_minutes", 60)
        m_type = item.get("meeting_type", MeetingType.ONLINE)
        days = item.get("days", ["saturday"])
        url = item.get("meeting_url")
        loc = item.get("location")

        pref = learn_student_preferred_hour(db, s_id, tutor.timezone)
        if pref:
            pref_time_str, pref_source = pref
            pref_h, pref_m = map(int, pref_time_str.split(":"))
            pref_time = time(pref_h, pref_m)
        else:
            pref_time = time(16, 0)
            pref_source = "Manual selection (first two weeks / insufficient history)"

        for day_name in days:
            offset = DAY_OFFSETS.get(day_name.lower().strip(), 0)
            meeting_date = target_week_start + timedelta(days=offset)

            assigned_time = find_available_slot(
                db=db,
                tutor_id=tutor.id,
                target_date=meeting_date,
                preferred_time_obj=pref_time,
                duration_minutes=dur,
                tz_name=tutor.timezone,
                booked_slots=booked_slots,
            )
            final_time = assigned_time or pref_time
            time_str = final_time.strftime("%H:%M")

            utc_start, utc_end = calculate_utc_datetimes(meeting_date, final_time, dur, tutor.timezone)
            booked_slots.append((utc_start, utc_end))

            p_item = WeeklyScheduleItem(
                proposal_id=proposal.id,
                student_id=s_id,
                scheduled_date=meeting_date,
                start_time_str=time_str,
                duration_minutes=dur,
                meeting_type=m_type,
                meeting_url=url,
                location=loc,
                preference_source=pref_source,
                is_manually_adjusted=False,
            )
            db.add(p_item)

    db.commit()
    db.refresh(proposal)
    return proposal


def update_proposal_item(
    db: Session,
    item_id: uuid.UUID,
    scheduled_date: date,
    start_time_str: str,
    duration_minutes: int,
    meeting_type: MeetingType,
    notes: Optional[str] = None,
) -> WeeklyScheduleItem:
    """Manually adjust a proposed meeting item."""
    item = db.get(WeeklyScheduleItem, item_id)
    if not item:
        raise SchedulerError("Proposal item not found.")

    item.scheduled_date = scheduled_date
    item.start_time_str = start_time_str
    item.duration_minutes = duration_minutes
    item.meeting_type = meeting_type
    item.notes = notes
    item.is_manually_adjusted = True
    item.preference_source = "Manually adjusted by tutor"

    db.commit()
    db.refresh(item)
    return item


def regenerate_unadjusted_items(
    db: Session,
    proposal_id: uuid.UUID,
    tutor: User,
) -> WeeklyScheduleProposal:
    """
    Regenerate recommendations for items not marked as manually adjusted,
    without overwriting tutor's manual adjustments.
    """
    proposal = db.get(WeeklyScheduleProposal, proposal_id)
    if not proposal or proposal.tutor_id != tutor.id:
        raise SchedulerError("Proposal not found.")

    # Collect booked slots from manually adjusted items and existing DB meetings
    booked_slots: List[Tuple[datetime, datetime]] = []
    for item in proposal.items:
        if item.is_manually_adjusted:
            h, m = map(int, item.start_time_str.split(":"))
            utc_s, utc_e = calculate_utc_datetimes(item.scheduled_date, time(h, m), item.duration_minutes, tutor.timezone)
            booked_slots.append((utc_s, utc_e))

    for item in proposal.items:
        if item.is_manually_adjusted:
            continue

        pref = learn_student_preferred_hour(db, item.student_id, tutor.timezone)
        if pref:
            pref_time_str, pref_source = pref
            pref_h, pref_m = map(int, pref_time_str.split(":"))
            pref_time = time(pref_h, pref_m)
        else:
            pref_time = time(16, 0)
            pref_source = "Manual selection (insufficient history)"

        assigned = find_available_slot(
            db=db,
            tutor_id=tutor.id,
            target_date=item.scheduled_date,
            preferred_time_obj=pref_time,
            duration_minutes=item.duration_minutes,
            tz_name=tutor.timezone,
            booked_slots=booked_slots,
        )
        final_time = assigned or pref_time
        item.start_time_str = final_time.strftime("%H:%M")
        item.preference_source = pref_source

        utc_s, utc_e = calculate_utc_datetimes(item.scheduled_date, final_time, item.duration_minutes, tutor.timezone)
        booked_slots.append((utc_s, utc_e))

    proposal.updated_at = now_utc()
    db.commit()
    db.refresh(proposal)
    return proposal


def approve_weekly_proposal(
    db: Session,
    proposal_id: uuid.UUID,
    tutor: User,
) -> List[TutorMeeting]:
    """
    Approve proposed schedule, create TutorMeeting records, and deliver private in-app notifications.
    Idempotent: will not create duplicate meetings or duplicate notification messages.
    """
    proposal = db.get(WeeklyScheduleProposal, proposal_id)
    if not proposal or proposal.tutor_id != tutor.id:
        raise SchedulerError("Proposal not found.")

    if proposal.status == ProposalStatus.APPROVED:
        # Already approved, return existing meetings
        return [item.meeting for item in proposal.items if item.meeting]

    created_meetings: List[TutorMeeting] = []

    for item in proposal.items:
        h, m = map(int, item.start_time_str.split(":"))
        start_time_obj = time(h, m)

        meeting = create_meeting(
            db=db,
            tutor=tutor,
            student_id=item.student_id,
            meeting_date=item.scheduled_date,
            start_time_obj=start_time_obj,
            duration_minutes=item.duration_minutes,
            meeting_type=item.meeting_type,
            meeting_url=item.meeting_url,
            location=item.location,
            notes=item.notes,
            reminder_minutes=15,
        )
        item.meeting_id = meeting.id
        created_meetings.append(meeting)

        # Send private notification message to student
        student = db.get(User, item.student_id)
        if student:
            conv = get_or_create_conversation(db, student_id=student.id, tutor_id=tutor.id)
            loc_or_url = ""
            if item.meeting_type == MeetingType.ONLINE and item.meeting_url:
                loc_or_url = f"\nMeeting Link: {item.meeting_url}"
            elif item.meeting_type == MeetingType.OFFLINE and item.location:
                loc_or_url = f"\nLocation: {item.location}"

            msg_content = (
                f"📅 Weekly Session Scheduled\n"
                f"Hello {student.full_name}, your session has been scheduled:\n"
                f"• Date: {item.scheduled_date.strftime('%A, %B %d, %Y')}\n"
                f"• Time: {item.start_time_str} ({item.duration_minutes} minutes)\n"
                f"• Type: {'🌐 Online' if item.meeting_type == MeetingType.ONLINE else '📍 In-Person'}"
                f"{loc_or_url}"
            )
            send_message(db, conv.id, sender=tutor, content=msg_content)
            meeting.notification_sent_at = now_utc()

    proposal.status = ProposalStatus.APPROVED
    proposal.updated_at = now_utc()
    db.commit()
    return created_meetings


def quick_move_meeting(
    db: Session,
    meeting_id: uuid.UUID,
    tutor: User,
    target_date: date,
    target_time_str: str,
    duration_minutes: Optional[int] = None,
    notify_student: bool = True,
) -> TutorMeeting:
    """
    Move or swap a meeting to another slot, updating history and privately notifying the student.
    """
    meeting = db.get(TutorMeeting, meeting_id)
    if not meeting or meeting.tutor_id != tutor.id:
        raise SchedulerError("Meeting not found.")

    parts = target_time_str.split(":")
    new_time_obj = time(int(parts[0]), int(parts[1]))
    new_duration = duration_minutes or meeting.duration_minutes

    updated_meeting = reschedule_meeting(
        db=db,
        meeting_id=meeting.id,
        tutor=tutor,
        new_date=target_date,
        new_time_obj=new_time_obj,
        new_duration_minutes=new_duration,
        reason="Moved via Calendar Quick Swap",
    )

    if notify_student:
        student = db.get(User, meeting.student_id)
        if student:
            conv = get_or_create_conversation(db, student_id=student.id, tutor_id=tutor.id)
            local_start = to_local(updated_meeting.start_time, tutor.timezone)
            msg_content = (
                f"🔄 Session Rescheduled\n"
                f"Hello {student.full_name}, your upcoming session has been moved:\n"
                f"• New Date: {local_start.strftime('%A, %B %d, %Y')}\n"
                f"• New Time: {local_start.strftime('%H:%M')} ({updated_meeting.duration_minutes} minutes)\n"
                f"• Type: {'🌐 Online' if updated_meeting.meeting_type == MeetingType.ONLINE else '📍 In-Person'}"
            )
            send_message(db, conv.id, sender=tutor, content=msg_content)
            updated_meeting.notification_sent_at = now_utc()
            db.commit()

    return updated_meeting
