import json
import uuid
from datetime import date
from typing import Dict, List, Optional
from urllib.parse import quote
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.timezone import today_local
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
    bulk_add_manual_sessions,
    bulk_assign_occurrences_to_students,
    bulk_cancel_exam_sessions,
    bulk_remove_students_from_future_occurrences,
    bulk_restore_exam_sessions,
    bulk_skip_exam_sessions,
    cancel_exam_session,
    compare_students_on_session,
    configure_exam_grade_track,
    create_exam,
    create_exam_session,
    delete_exam_grade_track_config,
    delete_exam_session,
    dismiss_series_incompatible_assignment,
    evaluate_students_eligibility,
    extend_exam_recurrence,
    generate_series_sessions,
    get_all_series_incompatible_students,
    get_bulk_series_submission_overview,
    get_exam_by_id,
    get_exam_grade_track_config,
    get_exam_series_analytics,
    get_exam_session_by_id,
    get_student_comprehensive_analytics,
    get_student_exam_result_by_id,
    get_tutor_session_analytics,
    get_tutor_student_analytics,
    list_exam_audit_logs,
    list_exam_grade_track_configs,
    list_exam_sessions,
    list_exams,
    mark_exam_result_reviewed,
    reopen_exam_result,
    restore_archived_exam_series,
    restore_exam_session,
    safe_delete_exam_series,
    skip_exam_session,
    tutor_correct_exam_result,
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
    except (ValueError, ExamValidationError) as exc:
        err_msg = "Invalid date or numeric recurrence value." if isinstance(exc, ValueError) else str(exc)
        return templates.TemplateResponse(
            request=request,
            name="tutor/exams/create_exam.html",
            context={
                "error": err_msg,
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
    except (ValueError, ExamValidationError, ExamNotFoundError) as exc:
        err_msg = "Invalid date or numeric recurrence value." if isinstance(exc, ValueError) else str(exc)
        exam = get_exam_by_id(db, exam_id)
        return templates.TemplateResponse(
            request=request,
            name="tutor/exams/edit_exam.html",
            context={
                "exam": exam,
                "error": err_msg,
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
            url=f"/tutor/exams/{exam_id}?err={quote(str(exc), safe='')}",
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
            url=f"/tutor/exams/{exam_id}?err={quote(str(exc), safe='')}",
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
            "today_date": today_local(getattr(current_user, "timezone", None)).isoformat(),
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
                "today_date": today_local(getattr(current_user, "timezone", None)).isoformat(),
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


@router.post("/results/{result_id}/review")
def post_review_result(
    result_id: uuid.UUID,
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        res = mark_exam_result_reviewed(db, result_id, actor_id=current_user.id, notes=notes)
        return RedirectResponse(
            url=f"/tutor/exams/sessions/{res.exam_session_id}?msg=Result marked as reviewed",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except ExamResultNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/results/{result_id}/reopen")
def post_reopen_result(
    result_id: uuid.UUID,
    reason: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        res = reopen_exam_result(db, result_id, actor_id=current_user.id, reason=reason)
        return RedirectResponse(
            url=f"/tutor/exams/sessions/{res.exam_session_id}?msg=Result reopened for review",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except ExamResultNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/results/{result_id}/correct")
async def post_correct_result(
    request: Request,
    result_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = get_student_exam_result_by_id(db, result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found.")

    form_data = await request.form()
    rank_raw = form_data.get("overall_rank")
    notes = form_data.get("notes")
    reason = form_data.get("correction_reason")

    try:
        group_data = []
        for gr in result.group_results:
            key = gr.reporting_group_id or gr.id
            pct_val = form_data.get(f"group_{key}_percentage") or form_data.get(f"group_{gr.id}_percentage")
            if pct_val is not None and str(pct_val).strip():
                group_data.append({
                    "reporting_group_id": gr.reporting_group_id,
                    "group_title": gr.group_title,
                    "percentage": float(pct_val),
                    "included_subject_names": gr.included_subject_names,
                })

        clean_rank = int(rank_raw) if rank_raw and str(rank_raw).strip() else None
        res = tutor_correct_exam_result(
            db,
            result_id=result.id,
            actor_id=current_user.id,
            group_data=group_data if group_data else None,
            overall_rank=clean_rank,
            notes=str(notes) if notes else None,
            reason=str(reason) if reason else "Tutor correction",
        )
        return RedirectResponse(
            url=f"/tutor/exams/sessions/{res.exam_session_id}?msg=Result corrected successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except (ValueError, ExamValidationError) as exc:
        err_msg = "Please provide valid numeric percentage and rank values." if isinstance(exc, ValueError) else str(exc)
        return RedirectResponse(
            url=f"/tutor/exams/sessions/{result.exam_session_id}?err={quote(err_msg, safe='')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/{exam_id}/archive")
def post_archive_series(
    exam_id: uuid.UUID,
    reason: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        archive_exam(db, exam_id, actor_id=current_user.id, reason=reason)
        return RedirectResponse(
            url=f"/tutor/exams?msg=Exam series archived successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except ExamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{exam_id}/restore-archive")
def post_restore_archive_series(
    exam_id: uuid.UUID,
    reason: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        restore_archived_exam_series(db, exam_id, actor_id=current_user.id, reason=reason)
        return RedirectResponse(
            url=f"/tutor/exams/{exam_id}?msg=Exam series restored from archive",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except ExamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{exam_id}/delete")
def post_delete_series(
    exam_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        safe_delete_exam_series(db, exam_id, actor_id=current_user.id)
        return RedirectResponse(
            url="/tutor/exams?msg=Exam series deleted successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except ExamValidationError as exc:
        return RedirectResponse(
            url=f"/tutor/exams/{exam_id}?err={quote(str(exc), safe='')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/sessions/{session_id}/cancel")
def post_cancel_session(
    session_id: uuid.UUID,
    reason: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        sess = cancel_exam_session(db, session_id, actor_id=current_user.id, reason=reason)
        return RedirectResponse(
            url=f"/tutor/exams/{sess.exam_id}?msg=Occurrence on {sess.date} cancelled",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except ExamSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/sessions/{session_id}/delete")
def post_delete_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sess = get_exam_session_by_id(db, session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Occurrence not found.")
    exam_id = sess.exam_id
    try:
        delete_exam_session(db, session_id, actor_id=current_user.id)
        return RedirectResponse(
            url=f"/tutor/exams/{exam_id}?msg=Occurrence deleted successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except ExamValidationError as exc:
        return RedirectResponse(
            url=f"/tutor/exams/{exam_id}?err={quote(str(exc), safe='')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/sessions/bulk/action")
async def post_bulk_session_action(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    form_data = await request.form()
    action = form_data.get("bulk_action")
    session_ids_raw = form_data.getlist("session_ids")
    reason = form_data.get("reason")
    exam_id_raw = form_data.get("exam_id")

    redirect_url = f"/tutor/exams/{exam_id_raw}" if exam_id_raw else "/tutor/exams"
    try:
        session_ids = [uuid.UUID(str(sid)) for sid in session_ids_raw if sid]
    except ValueError:
        return RedirectResponse(url=f"{redirect_url}?err=Invalid+occurrence+identifier", status_code=status.HTTP_303_SEE_OTHER)

    if not session_ids:
        return RedirectResponse(url=f"{redirect_url}?err=No occurrences selected", status_code=status.HTTP_303_SEE_OTHER)

    if action == "skip":
        res = bulk_skip_exam_sessions(db, session_ids, actor_id=current_user.id, reason=str(reason) if reason else None)
        msg = f"{res['affected_count']} occurrence(s) marked as No Exam."
    elif action == "cancel":
        res = bulk_cancel_exam_sessions(db, session_ids, actor_id=current_user.id, reason=str(reason) if reason else None)
        msg = f"{res['affected_count']} occurrence(s) cancelled."
    elif action == "restore":
        res = bulk_restore_exam_sessions(db, session_ids, actor_id=current_user.id, reason=str(reason) if reason else None)
        msg = f"{res['affected_count']} occurrence(s) restored."
    else:
        msg = "Unknown action."

    return RedirectResponse(url=f"{redirect_url}?msg={msg}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{exam_id}/extend")
def post_extend_series_schedule(
    exam_id: uuid.UUID,
    new_end_date: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        new_last_date = date.fromisoformat(new_end_date)
        created = extend_exam_recurrence(db, exam_id, new_last_date, actor_id=current_user.id)
        return RedirectResponse(
            url=f"/tutor/exams/{exam_id}?msg=Schedule extended: {len(created)} new occurrences generated",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except (ValueError, ExamValidationError) as exc:
        return RedirectResponse(url=f"/tutor/exams/{exam_id}?err={quote(str(exc), safe='')}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{exam_id}/students/bulk-remove")
async def post_bulk_remove_students(
    request: Request,
    exam_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    form_data = await request.form()
    student_ids_raw = form_data.getlist("student_ids")
    try:
        student_ids = [uuid.UUID(str(sid)) for sid in student_ids_raw if sid]
    except ValueError:
        return RedirectResponse(url=f"/tutor/exams/{exam_id}?err=Invalid+student+identifier", status_code=status.HTTP_303_SEE_OTHER)
    if not student_ids:
        return RedirectResponse(url=f"/tutor/exams/{exam_id}?err=No students selected", status_code=status.HTTP_303_SEE_OTHER)

    res = bulk_remove_students_from_future_occurrences(db, exam_id, student_ids, actor_id=current_user.id)
    return RedirectResponse(
        url=f"/tutor/exams/{exam_id}?msg=Removed {res['affected_students_count']} student(s) from future occurrences ({res['removed_assignments_count']} assignments cancelled). Past results strictly preserved.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/bulk/overview", response_class=HTMLResponse)
def get_submission_overview_page(
    request: Request,
    exam_id: Optional[uuid.UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    overview = get_bulk_series_submission_overview(db, exam_id=exam_id)
    exams = list_exams(db, include_inactive=False)
    return templates.TemplateResponse(
        request=request,
        name="tutor/exams/submission_overview.html",
        context={
            "overview": overview,
            "exams": exams,
            "selected_exam_id": str(exam_id) if exam_id else None,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.get("/{exam_id}/audit-logs", response_class=HTMLResponse)
def get_series_audit_logs_page(
    request: Request,
    exam_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam series not found")
    logs = list_exam_audit_logs(db, exam_id=exam.id)
    return templates.TemplateResponse(
        request=request,
        name="tutor/exams/audit_logs.html",
        context={
            "exam": exam,
            "logs": logs,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.get("/sessions/{session_id}/compare", response_class=HTMLResponse)
def get_session_student_comparison_page(
    request: Request,
    session_id: uuid.UUID,
    grade: Optional[str] = None,
    track_id: Optional[uuid.UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    session = get_exam_session_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Exam session not found")
    comparison = compare_students_on_session(db, session_id=session_id, grade=grade, track_id=track_id)
    tracks = list_tracks(db)
    return templates.TemplateResponse(
        request=request,
        name="tutor/exams/compare_students.html",
        context={
            "session": session,
            "comparison": comparison,
            "tracks": tracks,
            "current_user": current_user,
            "current_session": current_session,
        },
    )
