import uuid
from datetime import date, datetime, time, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.dependencies import (
    get_current_session,
    get_current_user,
    require_tutor,
    verify_csrf_token,
)
from app.core.templates import templates
from app.core.timezone import get_timezone, now_utc, to_local
from app.models.meeting import (
    MeetingType,
    ProposalStatus,
    WeeklyScheduleItem,
    WeeklyScheduleProposal,
)
from app.models.session import UserSession
from app.models.user import User
from app.services.scheduler_service import (
    SchedulerError,
    approve_weekly_proposal,
    generate_weekly_proposal,
    get_target_week_start,
    learn_student_preferred_hour,
    quick_move_meeting,
    regenerate_unadjusted_items,
    update_proposal_item,
)
from app.services.user_service import list_students

router = APIRouter(
    prefix="/tutor",
    tags=["tutor-scheduler"],
    dependencies=[Depends(require_tutor), Depends(verify_csrf_token)],
)


@router.get("/scheduler", response_class=HTMLResponse)
def get_scheduler_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    target_week_start = get_target_week_start(tz_name=current_user.timezone)
    students = list_students(db, include_inactive=False)

    # Attach learned preference info for each student
    student_preferences = []
    for s in students:
        pref = learn_student_preferred_hour(db, s.id, current_user.timezone)
        student_preferences.append({
            "student": s,
            "pref": pref,
        })

    # Find latest draft proposal if any
    draft_proposal = (
        db.query(WeeklyScheduleProposal)
        .options(joinedload(WeeklyScheduleProposal.items).joinedload(WeeklyScheduleItem.student))
        .filter(
            WeeklyScheduleProposal.tutor_id == current_user.id,
            WeeklyScheduleProposal.status == ProposalStatus.DRAFT,
        )
        .order_by(WeeklyScheduleProposal.created_at.desc())
        .first()
    )

    return templates.TemplateResponse(
        request=request,
        name="tutor/scheduler/index.html",
        context={
            "request": request,
            "current_user": current_user,
            "current_session": current_session,
            "target_week_start": target_week_start,
            "target_week_end": target_week_start + timedelta(days=6),
            "student_preferences": student_preferences,
            "draft_proposal": draft_proposal,
        },
    )


@router.post("/scheduler/generate", response_class=HTMLResponse)
async def post_generate_schedule(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    form_data = await request.form()
    target_week_str = form_data.get("target_week_start")
    if target_week_str:
        target_week = datetime.strptime(str(target_week_str), "%Y-%m-%d").date()
    else:
        target_week = get_target_week_start(tz_name=current_user.timezone)

    selected_student_ids = form_data.getlist("selected_students")
    student_selections = []

    for s_id_str in selected_student_ids:
        s_id = uuid.UUID(s_id_str)
        days = form_data.getlist(f"days_{s_id_str}")
        if not days:
            days = ["saturday"]
        dur = int(form_data.get(f"duration_{s_id_str}", 60))
        m_type_str = str(form_data.get(f"type_{s_id_str}", "ONLINE"))
        m_type = MeetingType.OFFLINE if m_type_str == "OFFLINE" else MeetingType.ONLINE
        url = form_data.get(f"url_{s_id_str}")
        loc = form_data.get(f"loc_{s_id_str}")

        student_selections.append({
            "student_id": s_id,
            "days": days,
            "duration_minutes": dur,
            "meeting_type": m_type,
            "meeting_url": str(url) if url else None,
            "location": str(loc) if loc else None,
        })

    proposal = generate_weekly_proposal(
        db=db,
        tutor=current_user,
        target_week_start=target_week,
        student_selections=student_selections,
    )
    return RedirectResponse(url=f"/tutor/scheduler/proposals/{proposal.id}", status_code=303)


@router.get("/scheduler/proposals/{proposal_id}", response_class=HTMLResponse)
def get_proposal_review(
    proposal_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    proposal = (
        db.query(WeeklyScheduleProposal)
        .options(joinedload(WeeklyScheduleProposal.items).joinedload(WeeklyScheduleItem.student))
        .filter(WeeklyScheduleProposal.id == proposal_id, WeeklyScheduleProposal.tutor_id == current_user.id)
        .first()
    )
    if not proposal:
        raise HTTPException(status_code=404, detail="Schedule proposal not found.")

    return templates.TemplateResponse(
        request=request,
        name="tutor/scheduler/review.html",
        context={
            "request": request,
            "current_user": current_user,
            "current_session": current_session,
            "proposal": proposal,
        },
    )


@router.post("/scheduler/proposals/{proposal_id}/items/{item_id}", response_class=HTMLResponse)
def post_update_proposal_item(
    proposal_id: uuid.UUID,
    item_id: uuid.UUID,
    scheduled_date: str = Form(...),
    start_time: str = Form(...),
    duration_minutes: int = Form(...),
    meeting_type: str = Form("ONLINE"),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    p_date = datetime.strptime(scheduled_date, "%Y-%m-%d").date()
    m_type = MeetingType.OFFLINE if meeting_type == "OFFLINE" else MeetingType.ONLINE

    update_proposal_item(
        db=db,
        item_id=item_id,
        scheduled_date=p_date,
        start_time_str=start_time,
        duration_minutes=duration_minutes,
        meeting_type=m_type,
        notes=notes,
    )
    return RedirectResponse(url=f"/tutor/scheduler/proposals/{proposal_id}", status_code=303)


@router.post("/scheduler/proposals/{proposal_id}/regenerate", response_class=HTMLResponse)
def post_regenerate_proposal(
    proposal_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    regenerate_unadjusted_items(db, proposal_id, current_user)
    return RedirectResponse(url=f"/tutor/scheduler/proposals/{proposal_id}", status_code=303)


@router.post("/scheduler/proposals/{proposal_id}/approve", response_class=HTMLResponse)
def post_approve_proposal(
    proposal_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    proposal = db.get(WeeklyScheduleProposal, proposal_id)
    if not proposal or proposal.tutor_id != current_user.id:
        raise HTTPException(status_code=404, detail="Proposal not found.")

    approve_weekly_proposal(db, proposal_id, current_user)
    target_date_str = proposal.target_week_start.strftime("%Y-%m-%d")
    return RedirectResponse(url=f"/tutor/calendar?date={target_date_str}&approved=1", status_code=303)


@router.post("/meetings/{meeting_id}/quick-move", response_class=HTMLResponse)
def post_quick_move(
    meeting_id: uuid.UUID,
    request: Request,
    target_date: str = Form(...),
    target_time: str = Form(...),
    notify: bool = Form(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Handle drag-and-drop or quick time swap for a meeting,
    updating history, checking conflicts, and privately notifying the student.
    """
    t_date = datetime.strptime(target_date.strip(), "%Y-%m-%d").date()
    try:
        quick_move_meeting(
            db=db,
            meeting_id=meeting_id,
            tutor=current_user,
            target_date=t_date,
            target_time_str=target_time.strip(),
            notify_student=notify,
        )
    except Exception as e:
        if request.headers.get("HX-Request"):
            return Response(content=f"<script>alert('{str(e)}');</script>", status_code=400)
        raise HTTPException(status_code=400, detail=str(e))

    if request.headers.get("HX-Request"):
        response = Response(status_code=200)
        response.headers["HX-Trigger"] = "meetingChanged"
        return response

    return RedirectResponse(url=f"/tutor/calendar?date={target_date}", status_code=303)
