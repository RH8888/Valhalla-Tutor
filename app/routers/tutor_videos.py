import uuid
from typing import Optional
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
from app.services.academic_service import list_subjects
from app.services.resource_service import (
    CourseChapterNotFoundError,
    CourseNotFoundError,
    create_course,
    create_course_chapter,
    delete_course,
    delete_course_chapter,
    get_course_by_id,
    list_courses,
    update_course,
    update_course_chapter,
)

router = APIRouter(
    prefix="/tutor/videos",
    tags=["tutor-videos"],
    dependencies=[Depends(require_tutor), Depends(verify_csrf_token)],
)


@router.get("", response_class=HTMLResponse)
def get_videos_dashboard(
    request: Request,
    subject_id: Optional[uuid.UUID] = None,
    msg: Optional[str] = None,
    err: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    subjects = list_subjects(db)
    courses = list_courses(db, subject_id=subject_id)

    return templates.TemplateResponse(
        request=request,
        name="tutor/videos/list.html",
        context={
            "subjects": subjects,
            "selected_subject_id": subject_id,
            "courses": courses,
            "message": msg,
            "error": err,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.get("/courses/create", response_class=HTMLResponse)
def get_create_course_page(
    request: Request,
    subject_id: Optional[uuid.UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    subjects = list_subjects(db)
    return templates.TemplateResponse(
        request=request,
        name="tutor/videos/create_course.html",
        context={
            "subjects": subjects,
            "selected_subject_id": subject_id,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("/courses", response_class=HTMLResponse)
def post_create_course(
    request: Request,
    subject_id: uuid.UUID = Form(...),
    teacher_name: str = Form(...),
    name: str = Form(...),
    grade: str = Form(...),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    try:
        course = create_course(
            db=db,
            subject_id=subject_id,
            teacher_name=teacher_name,
            name=name,
            grade=grade,
            description=description,
        )
        return RedirectResponse(
            url=f"/tutor/videos/courses/{course.id}?msg=Course created successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/tutor/videos?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.get("/courses/{course_id}", response_class=HTMLResponse)
def get_course_detail(
    request: Request,
    course_id: uuid.UUID,
    msg: Optional[str] = None,
    err: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    course = get_course_by_id(db, course_id)
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    return templates.TemplateResponse(
        request=request,
        name="tutor/videos/course_detail.html",
        context={
            "course": course,
            "message": msg,
            "error": err,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("/courses/{course_id}/edit")
def post_edit_course(
    course_id: uuid.UUID,
    teacher_name: str = Form(...),
    name: str = Form(...),
    grade: str = Form(...),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    try:
        update_course(
            db,
            course_id=course_id,
            teacher_name=teacher_name,
            name=name,
            grade=grade,
            description=description,
        )
        return RedirectResponse(
            url=f"/tutor/videos/courses/{course_id}?msg=Course updated successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/tutor/videos/courses/{course_id}?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/courses/{course_id}/delete")
def post_delete_course(
    course_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    try:
        delete_course(db, course_id)
        return RedirectResponse(
            url="/tutor/videos?msg=Course deleted successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/tutor/videos?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/courses/{course_id}/chapters")
def post_add_course_chapter(
    course_id: uuid.UUID,
    name: str = Form(...),
    video_count: int = Form(...),
    description: Optional[str] = Form(None),
    display_order: int = Form(1),
    db: Session = Depends(get_db),
):
    try:
        create_course_chapter(
            db=db,
            course_id=course_id,
            name=name,
            video_count=video_count,
            description=description,
            display_order=display_order,
        )
        return RedirectResponse(
            url=f"/tutor/videos/courses/{course_id}?msg=Chapter added successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/tutor/videos/courses/{course_id}?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/chapters/{chapter_id}/edit")
def post_edit_course_chapter(
    chapter_id: uuid.UUID,
    course_id: uuid.UUID = Form(...),
    name: str = Form(...),
    video_count: int = Form(...),
    description: Optional[str] = Form(None),
    display_order: int = Form(1),
    db: Session = Depends(get_db),
):
    try:
        update_course_chapter(
            db=db,
            chapter_id=chapter_id,
            name=name,
            video_count=video_count,
            description=description,
            display_order=display_order,
        )
        return RedirectResponse(
            url=f"/tutor/videos/courses/{course_id}?msg=Chapter updated successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/tutor/videos/courses/{course_id}?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/chapters/{chapter_id}/delete")
def post_delete_course_chapter(
    chapter_id: uuid.UUID,
    course_id: uuid.UUID = Form(...),
    db: Session = Depends(get_db),
):
    try:
        delete_course_chapter(db, chapter_id)
        return RedirectResponse(
            url=f"/tutor/videos/courses/{course_id}?msg=Chapter deleted successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/tutor/videos/courses/{course_id}?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

