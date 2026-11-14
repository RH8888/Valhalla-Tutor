import json
import uuid
from datetime import date
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_session, get_current_user, require_tutor, verify_csrf_token
from app.core.templates import templates
from app.models.session import UserSession
from app.models.user import User
from app.services.academic_service import list_tracks
from app.services.exam_service import (
    ExamNotFoundError,
    ExamSessionNotFoundError,
    ExamValidationError,
    archive_exam,
    create_exam,
    create_exam_session,
    get_exam_by_id,
    get_exam_session_by_id,
    get_tutor_session_analytics,
    get_tutor_student_analytics,
    list_exam_sessions,
    list_exams,
    update_exam,
)

router = APIRouter(
    prefix="/tutor/exams",
    tags=["tutor-exams"],
    dependencies=[Depends(require_tutor), Depends(verify_csrf_token)],
)


@router.get("", response_class=HTMLResponse)
def get_tutor_exams(
    request: Request,
    msg: Optional[str] = None,
    err: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    exams = list_exams(db, include_inactive=True)
    sessions = list_exam_sessions(db)
    return templates.TemplateResponse(
        request=request,
        name="tutor/exams/list.html",
        context={
            "exams": exams,
            "sessions": sessions,
            "msg": msg,
            "err": err,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.get("/create", response_class=HTMLResponse)
def get_create_exam_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    return templates.TemplateResponse(
        request=request,
        name="tutor/exams/create_exam.html",
        context={
            "error": None,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("/create")
def post_create_exam(
    request: Request,
    title: str = Form(...),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    try:
        create_exam(db, title=title, description=description)
        return RedirectResponse(
            url="/tutor/exams?msg=Exam definition created successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except ExamValidationError as exc:
        return templates.TemplateResponse(
            request=request,
            name="tutor/exams/create_exam.html",
            context={
                "error": str(exc),
                "title": title,
                "description": description,
                "current_user": current_user,
                "current_session": current_session,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )


@router.get("/{exam_id}/edit", response_class=HTMLResponse)
def get_edit_exam_form(
    request: Request,
    exam_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    return templates.TemplateResponse(
        request=request,
        name="tutor/exams/edit_exam.html",
        context={
            "exam": exam,
            "error": None,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("/{exam_id}/edit")
def post_edit_exam(
    request: Request,
    exam_id: uuid.UUID,
    title: str = Form(...),
    description: Optional[str] = Form(None),
    is_active: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    try:
        update_exam(
            db,
            exam_id=exam_id,
            title=title,
            description=description,
            is_active=is_active,
        )
        return RedirectResponse(
            url="/tutor/exams?msg=Exam updated successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except (ExamValidationError, ExamNotFoundError) as exc:
        exam = get_exam_by_id(db, exam_id)
        return templates.TemplateResponse(
            request=request,
            name="tutor/exams/edit_exam.html",
            context={
                "exam": exam,
                "error": str(exc),
                "current_user": current_user,
                "current_session": current_session,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )


@router.get("/sessions/create", response_class=HTMLResponse)
def get_create_session_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    active_exams = list_exams(db, include_inactive=False)
    tracks = list_tracks(db)
    return templates.TemplateResponse(
        request=request,
        name="tutor/exams/create_session.html",
        context={
            "active_exams": active_exams,
            "tracks": tracks,
            "error": None,
            "today_date": date.today().isoformat(),
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("/sessions/create")
async def post_create_session(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    form_data = await request.form()
    exam_id_raw = form_data.get("exam_id")
    date_raw = form_data.get("date")
    title = form_data.get("title")

    if not exam_id_raw or not date_raw:
        active_exams = list_exams(db, include_inactive=False)
        tracks = list_tracks(db)
        return templates.TemplateResponse(
            request=request,
            name="tutor/exams/create_session.html",
            context={
                "active_exams": active_exams,
                "tracks": tracks,
                "error": "Exam and date are required.",
                "today_date": date.today().isoformat(),
                "current_user": current_user,
                "current_session": current_session,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        exam_id = uuid.UUID(str(exam_id_raw))
        exam_date = date.fromisoformat(str(date_raw))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid exam ID or date format.")

    # Parse tracks and subjects
    track_ids_raw = form_data.getlist("track_ids")
    track_subjects_map: Dict[uuid.UUID, List[uuid.UUID]] = {}

    for t_id_str in track_ids_raw:
        try:
            t_id = uuid.UUID(str(t_id_str))
            # get subjects for this track: e.g. form fields named "track_{t_id}_subjects"
            sub_ids_raw = form_data.getlist(f"track_{t_id}_subjects")
            sub_ids = [uuid.UUID(str(sid)) for sid in sub_ids_raw if sid]
            track_subjects_map[t_id] = sub_ids
        except (ValueError, TypeError):
            continue

    try:
        session = create_exam_session(
            db,
            exam_id=exam_id,
            exam_date=exam_date,
            title=str(title) if title else None,
            track_subjects_map=track_subjects_map,
        )
        return RedirectResponse(
            url=f"/tutor/exams/sessions/{session.id}?msg=Exam session scheduled successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except (ExamValidationError, ExamNotFoundError) as exc:
        active_exams = list_exams(db, include_inactive=False)
        tracks = list_tracks(db)
        return templates.TemplateResponse(
            request=request,
            name="tutor/exams/create_session.html",
            context={
                "active_exams": active_exams,
                "tracks": tracks,
                "error": str(exc),
                "today_date": str(date_raw),
                "current_user": current_user,
                "current_session": current_session,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )


@router.get("/sessions/{session_id}", response_class=HTMLResponse)
def get_session_detail(
    request: Request,
    session_id: uuid.UUID,
    msg: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    session = get_exam_session_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Exam session not found")

    analytics = get_tutor_session_analytics(db, session_id)
    return templates.TemplateResponse(
        request=request,
        name="tutor/exams/session_detail.html",
        context={
            "session": session,
            "analytics": analytics,
            "msg": msg,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.get("/students/{student_id}", response_class=HTMLResponse)
def get_tutor_student_analytics_page(
    request: Request,
    student_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    data = get_tutor_student_analytics(db, student_id)
    return templates.TemplateResponse(
        request=request,
        name="tutor/exams/student_analytics.html",
        context={
            "student": data["student"],
            "analytics": data["analytics"],
            "analytics_json": json.dumps(data["analytics"]),
            "current_user": current_user,
            "current_session": current_session,
        },
    )
