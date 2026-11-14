import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import (
    get_current_session,
    get_current_user,
    require_tutor,
    verify_csrf_token,
)
from app.core.templates import templates
from app.models.session import UserSession
from app.models.user import User
from app.services.academic_service import (
    assign_student_track,
    customize_student_subjects,
    get_student_effective_subjects,
    list_subjects,
    list_tracks,
    reset_student_subjects_to_track,
)
from app.services.plan_service import (
    get_assignment,
    get_assignment_audit_logs,
    get_student_monitoring_data,
    reset_assignment_completion,
)
from app.services.user_service import (
    UserAlreadyExistsError,
    UserNotFoundError,
    create_student,
    get_student_by_id,
    list_students,
    reset_student_password,
    set_student_active_status,
)

router = APIRouter(
    prefix="/tutor",
    tags=["tutor"],
    dependencies=[Depends(require_tutor), Depends(verify_csrf_token)],
)


@router.get("/students", response_class=HTMLResponse)
def get_students_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    students = list_students(db, include_inactive=True)
    return templates.TemplateResponse(
        request=request,
        name="tutor/students/list.html",
        context={
            "students": students,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.get("/students/create", response_class=HTMLResponse)
def get_create_student_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    return templates.TemplateResponse(
        request=request,
        name="tutor/students/create.html",
        context={
            "error": None,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("/students")
def post_create_student(
    request: Request,
    full_name: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    email: Optional[str] = Form(None),
    timezone: str = Form("Asia/Tehran"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    try:
        student = create_student(
            db=db,
            username=username,
            full_name=full_name,
            password=password,
            email=email,
            timezone=timezone,
        )
        return RedirectResponse(
            url=f"/tutor/students/{student.id}?msg=Student account created",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except UserAlreadyExistsError as exc:
        return templates.TemplateResponse(
            request=request,
            name="tutor/students/create.html",
            context={
                "error": str(exc),
                "full_name": full_name,
                "username": username,
                "email": email,
                "timezone": timezone,
                "current_user": current_user,
                "current_session": current_session,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )


@router.get("/students/{student_id}", response_class=HTMLResponse)
def get_student_detail(
    request: Request,
    student_id: uuid.UUID,
    msg: Optional[str] = None,
    err: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    student = get_student_by_id(db, student_id)
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    tracks = list_tracks(db)
    all_subjects = list_subjects(db)
    effective_subjects = get_student_effective_subjects(student)
    custom_subject_ids = {s.id for s in student.custom_subjects}
    monitoring_data = get_student_monitoring_data(db, student_id)

    return templates.TemplateResponse(
        request=request,
        name="tutor/students/detail.html",
        context={
            "student": student,
            "tracks": tracks,
            "all_subjects": all_subjects,
            "effective_subjects": effective_subjects,
            "custom_subject_ids": custom_subject_ids,
            "monitoring": monitoring_data,
            "message": msg,
            "error": err,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("/students/{student_id}/assign-track")
def post_assign_student_track(
    student_id: uuid.UUID,
    track_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    try:
        t_id = uuid.UUID(track_id.strip()) if track_id and track_id.strip() else None
        assign_student_track(db, student_id=student_id, track_id=t_id)
        return RedirectResponse(
            url=f"/tutor/students/{student_id}?msg=Academic track updated successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/tutor/students/{student_id}?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/students/{student_id}/customize-subjects")
def post_customize_student_subjects(
    student_id: uuid.UUID,
    subject_ids: List[uuid.UUID] = Form(default=[]),
    db: Session = Depends(get_db),
):
    try:
        customize_student_subjects(db, student_id=student_id, subject_ids=subject_ids)
        return RedirectResponse(
            url=f"/tutor/students/{student_id}?msg=Student subjects customized successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/tutor/students/{student_id}?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/students/{student_id}/reset-subjects")
def post_reset_student_subjects(
    student_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    try:
        reset_student_subjects_to_track(db, student_id=student_id)
        return RedirectResponse(
            url=f"/tutor/students/{student_id}?msg=Student subjects reset to track defaults",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/tutor/students/{student_id}?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/students/{student_id}/toggle-status")
def post_toggle_student_status(
    student_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    student = get_student_by_id(db, student_id)
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    new_status = not student.is_active
    set_student_active_status(db, student_id, new_status)
    action = "activated" if new_status else "deactivated"
    return RedirectResponse(
        url=f"/tutor/students/{student_id}?msg=Account successfully {action}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/students/{student_id}/reset-password")
def post_reset_student_password(
    student_id: uuid.UUID,
    new_password: str = Form(...),
    db: Session = Depends(get_db),
):
    if not new_password or not new_password.strip():
        return RedirectResponse(
            url=f"/tutor/students/{student_id}?err=Password cannot be empty",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        reset_student_password(db, student_id, new_password.strip())
        return RedirectResponse(
            url=f"/tutor/students/{student_id}?msg=Password reset successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except UserNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")


@router.post("/assignments/{assignment_id}/reset-completion")
def post_reset_assignment_completion(
    assignment_id: uuid.UUID,
    request: Request,
    note: Optional[str] = Form(None),
    redirect_url: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assignment = get_assignment(db, assignment_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    student_id = assignment.student_id
    updated_assignment = reset_assignment_completion(
        db=db,
        assignment_id=assignment_id,
        tutor_id=current_user.id,
        note=note,
    )

    if request.headers.get("HX-Request"):
        return HTMLResponse(
            f'<div id="assignment-status-{assignment_id}" class="text-xs text-amber-700 font-bold bg-amber-50 px-2 py-1 rounded border border-amber-200">Reset to Pending ✓</div>'
        )

    target_url = redirect_url or f"/tutor/students/{student_id}?msg=Assignment completion was reset."
    return RedirectResponse(url=target_url, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/assignments/{assignment_id}/audits", response_class=HTMLResponse)
def get_assignment_audits_view(
    assignment_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    assignment = get_assignment(db, assignment_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    audits = get_assignment_audit_logs(db, assignment_id)
    return templates.TemplateResponse(
        request=request,
        name="tutor/plans/assignment_audits.html",
        context={
            "assignment": assignment,
            "audits": audits,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


