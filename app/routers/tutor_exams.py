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
from app.services.academic_service import get_track_by_id, list_tracks
from app.services.exam_service import (
    ExamNotFoundError,
    ExamSessionNotFoundError,
    ExamValidationError,
    IneligibleStudentError,
    add_manual_replacement_session,
    archive_exam,
    assign_exam_series_to_students,
    configure_exam_grade_track,
    create_exam,
    create_exam_session,
    delete_exam_grade_track_config,
    dismiss_series_incompatible_assignment,
    evaluate_students_eligibility,
    generate_series_sessions,
    get_all_series_incompatible_students,
    get_exam_by_id,
    get_exam_grade_track_config,
    get_exam_session_by_id,
    get_tutor_session_analytics,
    get_tutor_student_analytics,
    list_exam_grade_track_configs,
    list_exam_sessions,
    list_exams,
    restore_exam_session,
    skip_exam_session,
    update_exam,
    update_future_recurrence,
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
    profile_alerts = get_all_series_incompatible_students(db)
    return templates.TemplateResponse(
        request=request,
        name="tutor/exams/list.html",
        context={
            "exams": exams,
            "sessions": sessions,
            "profile_alerts": profile_alerts,
            "msg": msg,
            "err": err,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.get("/alerts/profile-changes", response_class=HTMLResponse)
def get_profile_change_alerts_page(
    request: Request,
    msg: Optional[str] = None,
    err: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    alerts = get_all_series_incompatible_students(db)
    return templates.TemplateResponse(
        request=request,
        name="tutor/exams/profile_alerts.html",
        context={
            "alerts": alerts,
            "msg": msg,
            "err": err,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("/alerts/profile-changes/{assignment_id}/dismiss")
def post_dismiss_profile_alert(
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dismiss_series_incompatible_assignment(db, assignment_id)
    return RedirectResponse(
        url="/tutor/exams/alerts/profile-changes?msg=Incompatible series assignment dismissed. Historical results were preserved.",
        status_code=status.HTTP_303_SEE_OTHER,
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
    first_exam_date: Optional[str] = Form(None),
    last_exam_date: Optional[str] = Form(None),
    recurrence_interval_weeks: Optional[str] = Form(None),
    recurrence_weekday: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    try:
        f_date = date.fromisoformat(first_exam_date) if first_exam_date and first_exam_date.strip() else None
        l_date = date.fromisoformat(last_exam_date) if last_exam_date and last_exam_date.strip() else None
        r_interval = int(recurrence_interval_weeks) if recurrence_interval_weeks and recurrence_interval_weeks.strip() else None
        r_weekday = int(recurrence_weekday) if recurrence_weekday and recurrence_weekday.strip() else None

        exam = create_exam(
            db,
            title=title,
            description=description,
            first_exam_date=f_date,
            last_exam_date=l_date,
            recurrence_interval_weeks=r_interval,
            recurrence_weekday=r_weekday,
        )
        return RedirectResponse(
            url=f"/tutor/exams/{exam.id}?msg=Exam definition created successfully",
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
                "first_exam_date": first_exam_date,
                "last_exam_date": last_exam_date,
                "recurrence_interval_weeks": recurrence_interval_weeks,
                "recurrence_weekday": recurrence_weekday,
                "current_user": current_user,
                "current_session": current_session,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )


@router.get("/{exam_id}", response_class=HTMLResponse)
def get_exam_series_detail(
    request: Request,
    exam_id: uuid.UUID,
    msg: Optional[str] = None,
    err: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam series not found")
    return templates.TemplateResponse(
        request=request,
        name="tutor/exams/series_detail.html",
        context={
            "exam": exam,
            "msg": msg,
            "err": err,
            "current_user": current_user,
            "current_session": current_session,
        },
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
    first_exam_date: Optional[str] = Form(None),
    last_exam_date: Optional[str] = Form(None),
    recurrence_interval_weeks: Optional[str] = Form(None),
    recurrence_weekday: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    try:
        f_date = date.fromisoformat(first_exam_date) if first_exam_date and first_exam_date.strip() else None
        l_date = date.fromisoformat(last_exam_date) if last_exam_date and last_exam_date.strip() else None
        r_interval = int(recurrence_interval_weeks) if recurrence_interval_weeks and recurrence_interval_weeks.strip() else None
        r_weekday = int(recurrence_weekday) if recurrence_weekday and recurrence_weekday.strip() else None

        update_exam(
            db,
            exam_id=exam_id,
            title=title,
            description=description,
            is_active=is_active,
            first_exam_date=f_date,
            last_exam_date=l_date,
            recurrence_interval_weeks=r_interval,
            recurrence_weekday=r_weekday,
        )
        return RedirectResponse(
            url=f"/tutor/exams/{exam_id}?msg=Exam updated successfully",
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


@router.get("/{exam_id}/grade-tracks/create", response_class=HTMLResponse)
def get_configure_grade_track_form(
    request: Request,
    exam_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam series not found")
    tracks = list_tracks(db)
    return templates.TemplateResponse(
        request=request,
        name="tutor/exams/configure_grade_track.html",
        context={
            "exam": exam,
            "tracks": tracks,
            "error": None,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("/{exam_id}/grade-tracks/create")
async def post_configure_grade_track(
    request: Request,
    exam_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam series not found")

    form_data = await request.form()
    grade = str(form_data.get("grade", "")).strip()
    track_id_raw = form_data.get("track_id")
    if not track_id_raw or not grade:
        raise HTTPException(status_code=400, detail="Grade and track are required.")

    track_id = uuid.UUID(str(track_id_raw))
    track = get_track_by_id(db, track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Academic track not found")

    track_sub_ids = {s.id for s in track.subjects}
    selected_subject_ids_raw = form_data.getlist("selected_subjects")
    selected_subject_ids = [
        uuid.UUID(str(sid)) for sid in selected_subject_ids_raw
        if sid and uuid.UUID(str(sid)) in track_sub_ids
    ]

    groups_map: Dict[str, List[uuid.UUID]] = {}
    for sid in selected_subject_ids:
        grp_name = str(form_data.get(f"subject_group_{sid}", "")).strip()
        if not grp_name:
            sub = db.query(Subject).filter(Subject.id == sid).first()
            grp_name = sub.name if sub else str(sid)
        if grp_name not in groups_map:
            groups_map[grp_name] = []
        groups_map[grp_name].append(sid)

    reporting_groups_data = [
        {"title": g_title, "order_index": idx, "subject_ids": s_ids}
        for idx, (g_title, s_ids) in enumerate(groups_map.items())
    ]

    try:
        configure_exam_grade_track(db, exam_id, grade, track_id, reporting_groups_data)
        return RedirectResponse(
            url=f"/tutor/exams/{exam_id}?msg=Grade and track reporting structure configured successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except ExamValidationError as exc:
        tracks = list_tracks(db)
        return templates.TemplateResponse(
            request=request,
            name="tutor/exams/configure_grade_track.html",
            context={
                "exam": exam,
                "tracks": tracks,
                "error": str(exc),
                "current_user": current_user,
                "current_session": current_session,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )


@router.post("/{exam_id}/grade-tracks/{config_id}/delete")
def post_delete_grade_track(
    exam_id: uuid.UUID,
    config_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    delete_exam_grade_track_config(db, config_id)
    return RedirectResponse(
        url=f"/tutor/exams/{exam_id}?msg=Grade/track configuration removed",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{exam_id}/schedule/generate")
def post_generate_schedule(
    exam_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        sessions = generate_series_sessions(db, exam_id, actor_id=current_user.id)
        return RedirectResponse(
            url=f"/tutor/exams/{exam_id}?msg=Generated {len(sessions)} scheduled occurrence(s)",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except ExamValidationError as exc:
        return RedirectResponse(
            url=f"/tutor/exams/{exam_id}?err={exc}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/sessions/{session_id}/skip")
def post_skip_session(
    session_id: uuid.UUID,
    reason: Optional[str] = Form(None),
    force: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        session = skip_exam_session(db, session_id, actor_id=current_user.id, reason=reason, force_if_results=force)
        return RedirectResponse(
            url=f"/tutor/exams/{session.exam_id}?msg=Occurrence on {session.date} marked as No Exam (skipped)",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except ExamValidationError as exc:
        session = get_exam_session_by_id(db, session_id)
        redirect_url = f"/tutor/exams/{session.exam_id}" if session else "/tutor/exams"
        return RedirectResponse(
            url=f"{redirect_url}?err={exc}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/sessions/{session_id}/restore")
def post_restore_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = restore_exam_session(db, session_id, actor_id=current_user.id)
    return RedirectResponse(
        url=f"/tutor/exams/{session.exam_id}?msg=Occurrence on {session.date} restored to Scheduled",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{exam_id}/sessions/manual")
def post_add_manual_session(
    exam_id: uuid.UUID,
    manual_date: str = Form(...),
    title: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        d = date.fromisoformat(manual_date)
        session = add_manual_replacement_session(db, exam_id, d, title=title, actor_id=current_user.id)
        return RedirectResponse(
            url=f"/tutor/exams/{exam_id}?msg=Manual occurrence on {session.date} added",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except (ValueError, ExamValidationError) as exc:
        return RedirectResponse(
            url=f"/tutor/exams/{exam_id}?err={exc}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.get("/{exam_id}/assignments", response_class=HTMLResponse)
def get_assign_students_page(
    request: Request,
    exam_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam series not found")

    all_students = db.query(User).filter(User.role == "STUDENT", User.is_active == True).order_by(User.full_name).all()
    student_ids = [s.id for s in all_students]
    eval_result = evaluate_students_eligibility(db, exam_id, student_ids)

    currently_assigned_ids = {sa.student_id for sa in exam.series_assignments}

    return templates.TemplateResponse(
        request=request,
        name="tutor/exams/assign_students.html",
        context={
            "exam": exam,
            "eligible": eval_result["eligible"],
            "ineligible": eval_result["ineligible"],
            "currently_assigned_ids": currently_assigned_ids,
            "error": None,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("/{exam_id}/assignments")
async def post_assign_students(
    request: Request,
    exam_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam series not found")

    form_data = await request.form()
    student_ids_raw = form_data.getlist("student_ids")
    student_ids = [uuid.UUID(str(sid)) for sid in student_ids_raw if sid]

    try:
        res = assign_exam_series_to_students(db, exam_id, student_ids)
        return RedirectResponse(
            url=f"/tutor/exams/{exam_id}?msg=Series assigned to {res['assigned_count']} student(s) successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except ExamValidationError as exc:
        all_students = db.query(User).filter(User.role == "STUDENT", User.is_active == True).all()
        eval_result = evaluate_students_eligibility(db, exam_id, [s.id for s in all_students])
        currently_assigned_ids = {sa.student_id for sa in exam.series_assignments}
        return templates.TemplateResponse(
            request=request,
            name="tutor/exams/assign_students.html",
            context={
                "exam": exam,
                "eligible": eval_result["eligible"],
                "ineligible": eval_result["ineligible"],
                "currently_assigned_ids": currently_assigned_ids,
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


@router.get("/results/{result_id}/report-card")
def download_tutor_exam_report_card(
    result_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = get_student_exam_result_by_id(db, result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found.")
    if not result.report_card_file_path:
        raise HTTPException(status_code=404, detail="No report card attachment uploaded.")

    from app.core.storage import get_absolute_file_path
    abs_path = get_absolute_file_path(result.report_card_file_path)
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="Report card file not found on disk.")

    from fastapi.responses import FileResponse
    return FileResponse(
        path=str(abs_path),
        filename=result.report_card_file_name or "report_card.pdf",
    )
