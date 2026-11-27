import calendar
import uuid
from datetime import date, datetime, time, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import (
    get_current_session,
    get_current_user,
    require_tutor,
    verify_csrf_token,
)
from app.core.i18n import (
    format_jalali,
    format_jalali_month_year,
    format_jalali_short,
    get_locale_from_request,
    translate_weekday,
)
from app.core.templates import templates
from app.core.timezone import get_timezone, now_utc, to_local, to_utc
from app.models.meeting import (
    MeetingReminder,
    MeetingRescheduleHistory,
    MeetingStatus,
    MeetingType,
    TutorMeeting,
)
from app.models.session import UserSession
from app.models.user import User
from app.services.meeting_service import (
    MeetingNotFoundError,
    MeetingOverlapError,
    MeetingServiceError,
    MeetingValidationError,
    create_meeting,
    dismiss_reminder,
    get_dashboard_meetings,
    get_due_reminders,
    get_meeting_by_id,
    list_tutor_meetings,
    reschedule_meeting,
    update_meeting_details,
    update_meeting_status,
)
from app.services.user_service import list_students

router = APIRouter(
    prefix="/tutor",
    tags=["tutor-calendar"],
    dependencies=[Depends(require_tutor), Depends(verify_csrf_token)],
)


def parse_date_or_today(date_str: Optional[str], tz_name: str) -> date:
    """Parse YYYY-MM-DD or return today's date in tutor's timezone."""
    if date_str:
        try:
            return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
        except ValueError:
            pass
    tz = get_timezone(tz_name)
    return datetime.now(tz).date()


def parse_time_or_default(time_str: Optional[str], default_hour: int = 10) -> time:
    """Parse HH:MM or return default time."""
    if time_str:
        try:
            parts = time_str.strip().split(":")
            return time(int(parts[0]), int(parts[1]))
        except Exception:
            pass
    return time(default_hour, 0)


def build_month_context(db: Session, tutor: User, current_date: date, locale: str = "en"):
    tz = get_timezone(tutor.timezone)
    year = current_date.year
    month = current_date.month

    # First day of month and last day of month
    _, last_day = calendar.monthrange(year, month)
    first_date = date(year, month, 1)
    last_date = date(year, month, last_day)

    # Calendar grid weeks
    cal = calendar.Calendar(firstweekday=5 if locale == "fa" else 0) # Saturday first in Persian, Monday first in English
    month_days = cal.monthdatescalendar(year, month)

    grid_start_utc = to_utc(datetime.combine(month_days[0][0], time.min, tzinfo=tz))
    grid_end_utc = to_utc(datetime.combine(month_days[-1][-1], time.max, tzinfo=tz))

    meetings = list_tutor_meetings(db, tutor.id, start_range=grid_start_utc, end_range=grid_end_utc)

    # Map meetings by local date string YYYY-MM-DD
    meetings_by_date = {}
    for m in meetings:
        local_start = to_local(m.start_time, tutor.timezone)
        d_key = local_start.strftime("%Y-%m-%d")
        if d_key not in meetings_by_date:
            meetings_by_date[d_key] = []
        meetings_by_date[d_key].append({
            "meeting": m,
            "local_start": local_start,
            "time_str": local_start.strftime("%H:%M"),
        })

    # Prev / Next month dates
    prev_month_date = (first_date - timedelta(days=1)).replace(day=1)
    next_month_date = (last_date + timedelta(days=1)).replace(day=1)

    title = format_jalali_month_year(current_date) if locale == "fa" else current_date.strftime("%B %Y")

    return {
        "view": "month",
        "current_date": current_date,
        "title": title,
        "month_days": month_days,
        "meetings_by_date": meetings_by_date,
        "prev_date": prev_month_date.strftime("%Y-%m-%d"),
        "next_date": next_month_date.strftime("%Y-%m-%d"),
        "today_date": datetime.now(tz).strftime("%Y-%m-%d"),
    }


def build_week_context(db: Session, tutor: User, current_date: date, locale: str = "en"):
    tz = get_timezone(tutor.timezone)
    # Week start: Saturday for Persian (weekday 5 -> offset 0), Monday for English
    if locale == "fa":
        offset = (current_date.weekday() - 5) % 7
        start_of_week = current_date - timedelta(days=offset)
    else:
        start_of_week = current_date - timedelta(days=current_date.weekday())
    week_days = [start_of_week + timedelta(days=i) for i in range(7)]

    start_utc = to_utc(datetime.combine(week_days[0], time.min, tzinfo=tz))
    end_utc = to_utc(datetime.combine(week_days[-1], time.max, tzinfo=tz))

    meetings = list_tutor_meetings(db, tutor.id, start_range=start_utc, end_range=end_utc)

    meetings_by_date = {}
    for m in meetings:
        local_start = to_local(m.start_time, tutor.timezone)
        d_key = local_start.strftime("%Y-%m-%d")
        if d_key not in meetings_by_date:
            meetings_by_date[d_key] = []
        meetings_by_date[d_key].append({
            "meeting": m,
            "local_start": local_start,
            "time_str": local_start.strftime("%H:%M"),
        })

    prev_week_date = current_date - timedelta(days=7)
    next_week_date = current_date + timedelta(days=7)

    title = (
        f"{format_jalali_short(week_days[0])} تا {format_jalali(week_days[-1])}"
        if locale == "fa"
        else f"{week_days[0].strftime('%b %d')} - {week_days[-1].strftime('%b %d, %Y')}"
    )

    return {
        "view": "week",
        "current_date": current_date,
        "title": title,
        "week_days": week_days,
        "meetings_by_date": meetings_by_date,
        "prev_date": prev_week_date.strftime("%Y-%m-%d"),
        "next_date": next_week_date.strftime("%Y-%m-%d"),
        "today_date": datetime.now(tz).strftime("%Y-%m-%d"),
    }


def build_day_context(db: Session, tutor: User, current_date: date, locale: str = "en"):
    tz = get_timezone(tutor.timezone)
    start_utc = to_utc(datetime.combine(current_date, time.min, tzinfo=tz))
    end_utc = to_utc(datetime.combine(current_date, time.max, tzinfo=tz))

    meetings = list_tutor_meetings(db, tutor.id, start_range=start_utc, end_range=end_utc)

    meetings_with_local = []
    for m in meetings:
        local_start = to_local(m.start_time, tutor.timezone)
        local_end = to_local(m.end_time, tutor.timezone)
        meetings_with_local.append({
            "meeting": m,
            "local_start": local_start,
            "local_end": local_end,
            "time_str": f"{local_start.strftime('%H:%M')} - {local_end.strftime('%H:%M')}",
        })

    prev_day = current_date - timedelta(days=1)
    next_day = current_date + timedelta(days=1)

    title = (
        f"{translate_weekday(current_date, 'fa')}، {format_jalali(current_date)}"
        if locale == "fa"
        else current_date.strftime("%A, %B %d, %Y")
    )

    return {
        "view": "day",
        "current_date": current_date,
        "title": title,
        "meetings": meetings_with_local,
        "hours": list(range(8, 22)), # 08:00 to 21:00
        "prev_date": prev_day.strftime("%Y-%m-%d"),
        "next_date": next_day.strftime("%Y-%m-%d"),
        "today_date": datetime.now(tz).strftime("%Y-%m-%d"),
    }


@router.get("/calendar", response_class=HTMLResponse)
def get_calendar(
    request: Request,
    view: str = Query("month", pattern="^(month|week|day)$"),
    date_str: Optional[str] = Query(None, alias="date"),
    partial: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    current_date = parse_date_or_today(date_str, current_user.timezone)
    locale = get_locale_from_request(request)

    if view == "week":
        cal_data = build_week_context(db, current_user, current_date, locale=locale)
    elif view == "day":
        cal_data = build_day_context(db, current_user, current_date, locale=locale)
    else:
        cal_data = build_month_context(db, current_user, current_date, locale=locale)

    context = {
        "request": request,
        "current_user": current_user,
        "current_session": current_session,
        "cal": cal_data,
        "view": view,
    }

    if partial or request.headers.get("HX-Target") == "calendar-view-container":
        template_name = f"tutor/calendar/partials/{view}_view.html"
        return templates.TemplateResponse(request=request, name=template_name, context=context)

    return templates.TemplateResponse(request=request, name="tutor/calendar/calendar.html", context=context)


@router.get("/dashboard", response_class=HTMLResponse)
def get_tutor_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    """Tutor dashboard showing student overview and upcoming meetings."""
    return RedirectResponse(url="/tutor/students", status_code=303)


@router.get("/meetings/new", response_class=HTMLResponse)
def get_create_meeting_modal(
    request: Request,
    date_str: Optional[str] = Query(None, alias="date"),
    time_str: Optional[str] = Query(None, alias="time"),
    student_id: Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    target_date = parse_date_or_today(date_str, current_user.timezone)
    students = list_students(db, include_inactive=False)

    return templates.TemplateResponse(
        request=request,
        name="tutor/calendar/partials/meeting_form.html",
        context={
            "request": request,
            "current_user": current_user,
            "current_session": current_session,
            "students": students,
            "default_date": target_date.strftime("%Y-%m-%d"),
            "default_time": time_str or "10:00",
            "selected_student_id": student_id,
            "meeting": None,
            "is_edit": False,
            "error": None,
        },
    )


@router.post("/meetings", response_class=HTMLResponse)
def post_create_meeting(
    request: Request,
    student_id: uuid.UUID = Form(...),
    meeting_date: str = Form(...),
    start_time: str = Form(...),
    duration_minutes: int = Form(...),
    meeting_type: str = Form("ONLINE"),
    meeting_url: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    reminder_minutes: Optional[str] = Form(None),
    view: str = Form("month"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    students = list_students(db, include_inactive=False)
    parsed_date = parse_date_or_today(meeting_date, current_user.timezone)
    parsed_time = parse_time_or_default(start_time)

    m_type = MeetingType.OFFLINE if meeting_type == "OFFLINE" else MeetingType.ONLINE

    try:
        if reminder_minutes and reminder_minutes.strip() not in ("", "none"):
            rem_val = int(reminder_minutes)
            if rem_val < 0:
                raise MeetingValidationError("Reminder minutes must be a non-negative integer.")
        else:
            rem_val = None

        create_meeting(
            db=db,
            tutor=current_user,
            student_id=student_id,
            meeting_date=parsed_date,
            start_time_obj=parsed_time,
            duration_minutes=duration_minutes,
            meeting_type=m_type,
            meeting_url=meeting_url,
            location=location,
            notes=notes,
            reminder_minutes=rem_val,
        )
    except (MeetingValidationError, MeetingOverlapError, ValueError) as e:
        err_msg = "Reminder minutes must be a valid non-negative integer." if isinstance(e, ValueError) else str(e)
        return templates.TemplateResponse(
            request=request,
            name="tutor/calendar/partials/meeting_form.html",
            context={
                "request": request,
                "current_user": current_user,
                "current_session": current_session,
                "students": students,
                "default_date": meeting_date,
                "default_time": start_time,
                "selected_student_id": student_id,
                "meeting": None,
                "is_edit": False,
                "error": err_msg,
                "duration_minutes": duration_minutes,
                "meeting_type": meeting_type,
                "meeting_url": meeting_url,
                "location": location,
                "notes": notes,
                "reminder_minutes": reminder_minutes,
            },
            status_code=400,
        )

    # Success: trigger calendar refresh via HTMX header
    response = Response(status_code=200)
    response.headers["HX-Trigger"] = "meetingChanged"
    return response


@router.get("/meetings/{meeting_id}", response_class=HTMLResponse)
def get_meeting_modal(
    meeting_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    try:
        meeting = get_meeting_by_id(db, meeting_id, tutor_id=current_user.id)
    except MeetingNotFoundError:
        raise HTTPException(status_code=404, detail="Meeting not found")

    local_start = to_local(meeting.start_time, current_user.timezone)
    local_end = to_local(meeting.end_time, current_user.timezone)

    return templates.TemplateResponse(
        request=request,
        name="tutor/calendar/partials/meeting_detail_modal.html",
        context={
            "request": request,
            "current_user": current_user,
            "current_session": current_session,
            "meeting": meeting,
            "local_start": local_start,
            "local_end": local_end,
            "time_str": f"{local_start.strftime('%H:%M')} - {local_end.strftime('%H:%M')}",
            "date_str": local_start.strftime("%A, %B %d, %Y"),
        },
    )


@router.get("/meetings/{meeting_id}/edit", response_class=HTMLResponse)
def get_edit_meeting_modal(
    meeting_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    try:
        meeting = get_meeting_by_id(db, meeting_id, tutor_id=current_user.id)
    except MeetingNotFoundError:
        raise HTTPException(status_code=404, detail="Meeting not found")
    students = list_students(db, include_inactive=True)
    local_start = to_local(meeting.start_time, current_user.timezone)

    return templates.TemplateResponse(
        request=request,
        name="tutor/calendar/partials/meeting_form.html",
        context={
            "request": request,
            "current_user": current_user,
            "current_session": current_session,
            "students": students,
            "default_date": local_start.strftime("%Y-%m-%d"),
            "default_time": local_start.strftime("%H:%M"),
            "selected_student_id": meeting.student_id,
            "meeting": meeting,
            "is_edit": True,
            "error": None,
        },
    )


@router.post("/meetings/{meeting_id}/edit", response_class=HTMLResponse)
def post_edit_meeting(
    meeting_id: uuid.UUID,
    request: Request,
    meeting_type: str = Form("ONLINE"),
    meeting_url: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    reminder_minutes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    m_type = MeetingType.OFFLINE if meeting_type == "OFFLINE" else MeetingType.ONLINE

    try:
        if reminder_minutes and reminder_minutes.strip() not in ("", "none"):
            rem_val = int(reminder_minutes)
            if rem_val < 0:
                raise MeetingValidationError("Reminder minutes must be a non-negative integer.")
        else:
            rem_val = None

        update_meeting_details(
            db=db,
            meeting_id=meeting_id,
            tutor=current_user,
            meeting_type=m_type,
            meeting_url=meeting_url,
            location=location,
            notes=notes,
            reminder_minutes=rem_val,
        )
    except MeetingNotFoundError:
        raise HTTPException(status_code=404, detail="Meeting not found")
    except (MeetingServiceError, ValueError) as e:
        err_msg = "Reminder minutes must be a valid non-negative integer." if isinstance(e, ValueError) else str(e)
        meeting = get_meeting_by_id(db, meeting_id, tutor_id=current_user.id)
        students = list_students(db, include_inactive=True)
        local_start = to_local(meeting.start_time, current_user.timezone)
        return templates.TemplateResponse(
            request=request,
            name="tutor/calendar/partials/meeting_form.html",
            context={
                "request": request,
                "current_user": current_user,
                "current_session": current_session,
                "students": students,
                "default_date": local_start.strftime("%Y-%m-%d"),
                "default_time": local_start.strftime("%H:%M"),
                "selected_student_id": meeting.student_id,
                "meeting": meeting,
                "is_edit": True,
                "error": err_msg,
            },
            status_code=400,
        )

    response = Response(status_code=200)
    response.headers["HX-Trigger"] = "meetingChanged"
    return response


@router.post("/meetings/{meeting_id}/reschedule", response_class=HTMLResponse)
def post_reschedule_meeting(
    meeting_id: uuid.UUID,
    request: Request,
    new_date: str = Form(...),
    new_time: str = Form(...),
    new_duration_minutes: int = Form(...),
    reason: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    parsed_date = parse_date_or_today(new_date, current_user.timezone)
    parsed_time = parse_time_or_default(new_time)

    try:
        reschedule_meeting(
            db=db,
            meeting_id=meeting_id,
            tutor=current_user,
            new_date=parsed_date,
            new_time_obj=parsed_time,
            new_duration_minutes=new_duration_minutes,
            reason=reason,
        )
    except MeetingNotFoundError:
        raise HTTPException(status_code=404, detail="Meeting not found")
    except (MeetingValidationError, MeetingOverlapError) as e:
        meeting = get_meeting_by_id(db, meeting_id, tutor_id=current_user.id)
        local_start = to_local(meeting.start_time, current_user.timezone)
        local_end = to_local(meeting.end_time, current_user.timezone)
        return templates.TemplateResponse(
            request=request,
            name="tutor/calendar/partials/meeting_detail_modal.html",
            context={
                "request": request,
                "current_user": current_user,
                "current_session": current_session,
                "meeting": meeting,
                "local_start": local_start,
                "local_end": local_end,
                "time_str": f"{local_start.strftime('%H:%M')} - {local_end.strftime('%H:%M')}",
                "date_str": local_start.strftime("%A, %B %d, %Y"),
                "error": str(e),
            },
            status_code=400,
        )

    response = Response(status_code=200)
    response.headers["HX-Trigger"] = "meetingChanged"
    return response


@router.post("/meetings/{meeting_id}/status", response_class=HTMLResponse)
def post_meeting_status(
    meeting_id: uuid.UUID,
    request: Request,
    new_status: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        status_enum = MeetingStatus(new_status)
        update_meeting_status(
            db=db,
            meeting_id=meeting_id,
            tutor=current_user,
            new_status=status_enum,
        )
    except MeetingNotFoundError:
        raise HTTPException(status_code=404, detail="Meeting not found")
    except (MeetingValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    response = Response(status_code=200)
    response.headers["HX-Trigger"] = "meetingChanged"
    return response


@router.get("/reminders/unread", response_class=HTMLResponse)
def get_unread_reminders(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    """Return active reminder badge and dropdown for navbar."""
    reminders = get_due_reminders(db, current_user.id)
    reminders_with_local = []
    for r in reminders:
        local_start = to_local(r.meeting.start_time, current_user.timezone)
        reminders_with_local.append({
            "reminder": r,
            "meeting": r.meeting,
            "time_str": local_start.strftime("%b %d, %H:%M"),
        })

    return templates.TemplateResponse(
        request=request,
        name="tutor/calendar/partials/reminder_indicator.html",
        context={
            "request": request,
            "current_user": current_user,
            "current_session": current_session,
            "reminders": reminders_with_local,
            "count": len(reminders_with_local),
        },
    )


@router.post("/reminders/{reminder_id}/dismiss", response_class=HTMLResponse)
def post_dismiss_reminder(
    reminder_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    """Dismiss reminder and re-render the indicator."""
    try:
        dismiss_reminder(db, reminder_id, current_user.id)
    except MeetingNotFoundError:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return get_unread_reminders(request, db, current_user, current_session)
