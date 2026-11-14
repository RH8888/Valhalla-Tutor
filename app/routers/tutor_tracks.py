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
    TrackAlreadyExistsError,
    TrackInUseError,
    TrackNotFoundError,
    add_subject_to_track,
    create_track,
    delete_track,
    get_track_by_id,
    list_subjects,
    list_tracks,
    remove_subject_from_track,
    update_track,
)

router = APIRouter(
    prefix="/tutor/tracks",
    tags=["tutor-tracks"],
    dependencies=[Depends(require_tutor), Depends(verify_csrf_token)],
)


@router.get("", response_class=HTMLResponse)
def get_tracks_list(
    request: Request,
    msg: Optional[str] = None,
    err: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    tracks = list_tracks(db)
    return templates.TemplateResponse(
        request=request,
        name="tutor/tracks/list.html",
        context={
            "tracks": tracks,
            "message": msg,
            "error": err,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.get("/create", response_class=HTMLResponse)
def get_create_track_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    all_subjects = list_subjects(db)
    return templates.TemplateResponse(
        request=request,
        name="tutor/tracks/create.html",
        context={
            "all_subjects": all_subjects,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("", response_class=HTMLResponse)
def post_create_track(
    request: Request,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    subject_ids: List[uuid.UUID] = Form(default=[]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    try:
        track = create_track(db, name=name, description=description, subject_ids=subject_ids)
        return RedirectResponse(
            url=f"/tutor/tracks/{track.id}?msg=Academic track created successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except (ValueError, TrackAlreadyExistsError) as exc:
        all_subjects = list_subjects(db)
        return templates.TemplateResponse(
            request=request,
            name="tutor/tracks/create.html",
            context={
                "error": str(exc),
                "name": name,
                "description": description,
                "all_subjects": all_subjects,
                "current_user": current_user,
                "current_session": current_session,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )


@router.get("/{track_id}", response_class=HTMLResponse)
def get_track_detail(
    request: Request,
    track_id: uuid.UUID,
    msg: Optional[str] = None,
    err: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    track = get_track_by_id(db, track_id)
    if not track:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Academic track not found")

    all_subjects = list_subjects(db)
    track_subject_ids = {s.id for s in track.subjects}
    available_subjects = [s for s in all_subjects if s.id not in track_subject_ids]

    return templates.TemplateResponse(
        request=request,
        name="tutor/tracks/detail.html",
        context={
            "track": track,
            "available_subjects": available_subjects,
            "message": msg,
            "error": err,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("/{track_id}/edit", response_class=HTMLResponse)
def post_edit_track(
    track_id: uuid.UUID,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    try:
        update_track(db, track_id=track_id, name=name, description=description)
        return RedirectResponse(
            url=f"/tutor/tracks/{track_id}?msg=Academic track updated successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except (ValueError, TrackAlreadyExistsError, TrackNotFoundError) as exc:
        return RedirectResponse(
            url=f"/tutor/tracks/{track_id}?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/{track_id}/subjects/add")
def post_add_subject_to_track(
    track_id: uuid.UUID,
    subject_id: uuid.UUID = Form(...),
    db: Session = Depends(get_db),
):
    try:
        add_subject_to_track(db, track_id=track_id, subject_id=subject_id)
        return RedirectResponse(
            url=f"/tutor/tracks/{track_id}?msg=Subject added to track",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/tutor/tracks/{track_id}?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/{track_id}/subjects/{subject_id}/remove")
def post_remove_subject_from_track(
    track_id: uuid.UUID,
    subject_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    try:
        remove_subject_from_track(db, track_id=track_id, subject_id=subject_id)
        return RedirectResponse(
            url=f"/tutor/tracks/{track_id}?msg=Subject removed from track",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/tutor/tracks/{track_id}?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/{track_id}/delete")
def post_delete_track(
    track_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    try:
        delete_track(db, track_id)
        return RedirectResponse(
            url="/tutor/tracks?msg=Academic track deleted successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except (TrackInUseError, TrackNotFoundError) as exc:
        return RedirectResponse(
            url=f"/tutor/tracks?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

