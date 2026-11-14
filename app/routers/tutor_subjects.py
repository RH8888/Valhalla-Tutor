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
    SubjectAlreadyExistsError,
    SubjectInUseError,
    SubjectNotFoundError,
    create_subject,
    delete_subject,
    get_subject_by_id,
    list_subjects,
    update_subject,
)

router = APIRouter(
    prefix="/tutor/subjects",
    tags=["tutor-subjects"],
    dependencies=[Depends(require_tutor), Depends(verify_csrf_token)],
)


@router.get("", response_class=HTMLResponse)
def get_subjects_list(
    request: Request,
    msg: Optional[str] = None,
    err: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    subjects = list_subjects(db)
    return templates.TemplateResponse(
        request=request,
        name="tutor/subjects/list.html",
        context={
            "subjects": subjects,
            "supported_grades": ["10", "11", "12"],
            "message": msg,
            "error": err,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("", response_class=HTMLResponse)
def post_create_subject(
    request: Request,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    grades: List[str] = Form(default=[]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    try:
        sub = create_subject(db, name=name, description=description, grades=grades or None)
        return RedirectResponse(
            url=f"/tutor/subjects?msg=Subject '{sub.name}' created successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except (ValueError, SubjectAlreadyExistsError) as exc:
        subjects = list_subjects(db)
        return templates.TemplateResponse(
            request=request,
            name="tutor/subjects/list.html",
            context={
                "subjects": subjects,
                "supported_grades": ["10", "11", "12"],
                "error": str(exc),
                "name": name,
                "description": description,
                "current_user": current_user,
                "current_session": current_session,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )


@router.get("/{subject_id}/edit", response_class=HTMLResponse)
def get_edit_subject_page(
    request: Request,
    subject_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    sub = get_subject_by_id(db, subject_id)
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")

    return templates.TemplateResponse(
        request=request,
        name="tutor/subjects/edit.html",
        context={
            "subject": sub,
            "supported_grades": ["10", "11", "12"],
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("/{subject_id}/edit", response_class=HTMLResponse)
def post_edit_subject(
    request: Request,
    subject_id: uuid.UUID,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    grades: List[str] = Form(default=[]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    try:
        sub = update_subject(db, subject_id=subject_id, name=name, description=description, grades=grades or None)
        return RedirectResponse(
            url=f"/tutor/subjects?msg=Subject '{sub.name}' updated successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except (ValueError, SubjectAlreadyExistsError, SubjectNotFoundError) as exc:
        sub = get_subject_by_id(db, subject_id)
        return templates.TemplateResponse(
            request=request,
            name="tutor/subjects/edit.html",
            context={
                "subject": sub,
                "supported_grades": ["10", "11", "12"],
                "error": str(exc),
                "current_user": current_user,
                "current_session": current_session,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )


@router.post("/{subject_id}/delete")
def post_delete_subject(
    subject_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    try:
        delete_subject(db, subject_id)
        return RedirectResponse(
            url="/tutor/subjects?msg=Subject deleted successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except (SubjectInUseError, SubjectNotFoundError) as exc:
        return RedirectResponse(
            url=f"/tutor/subjects?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

