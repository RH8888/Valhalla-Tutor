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
    BookChapterNotFoundError,
    BookNotFoundError,
    create_book,
    create_book_chapter,
    delete_book,
    delete_book_chapter,
    get_book_by_id,
    list_books,
    update_book,
    update_book_chapter,
)

router = APIRouter(
    prefix="/tutor/books",
    tags=["tutor-books"],
    dependencies=[Depends(require_tutor), Depends(verify_csrf_token)],
)


@router.get("", response_class=HTMLResponse)
def get_books_dashboard(
    request: Request,
    subject_id: Optional[uuid.UUID] = None,
    msg: Optional[str] = None,
    err: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    subjects = list_subjects(db)
    books = list_books(db, subject_id=subject_id)

    return templates.TemplateResponse(
        request=request,
        name="tutor/books/list.html",
        context={
            "subjects": subjects,
            "selected_subject_id": subject_id,
            "books": books,
            "message": msg,
            "error": err,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.get("/create", response_class=HTMLResponse)
def get_create_book_page(
    request: Request,
    subject_id: Optional[uuid.UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    subjects = list_subjects(db)
    return templates.TemplateResponse(
        request=request,
        name="tutor/books/create.html",
        context={
            "subjects": subjects,
            "selected_subject_id": subject_id,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("", response_class=HTMLResponse)
def post_create_book(
    request: Request,
    subject_id: uuid.UUID = Form(...),
    title: str = Form(...),
    grade: str = Form(...),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    try:
        book = create_book(
            db=db,
            subject_id=subject_id,
            title=title,
            grade=grade,
            description=description,
        )
        return RedirectResponse(
            url=f"/tutor/books/{book.id}?msg=Book created successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/tutor/books?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.get("/{book_id}", response_class=HTMLResponse)
def get_book_detail(
    request: Request,
    book_id: uuid.UUID,
    msg: Optional[str] = None,
    err: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    book = get_book_by_id(db, book_id)
    if not book:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")

    return templates.TemplateResponse(
        request=request,
        name="tutor/books/detail.html",
        context={
            "book": book,
            "message": msg,
            "error": err,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("/{book_id}/edit")
def post_edit_book(
    book_id: uuid.UUID,
    title: str = Form(...),
    grade: str = Form(...),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    try:
        update_book(
            db,
            book_id=book_id,
            title=title,
            grade=grade,
            description=description,
        )
        return RedirectResponse(
            url=f"/tutor/books/{book_id}?msg=Book updated successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/tutor/books/{book_id}?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/{book_id}/delete")
def post_delete_book(
    book_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    try:
        delete_book(db, book_id)
        return RedirectResponse(
            url="/tutor/books?msg=Book deleted successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/tutor/books?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/{book_id}/chapters")
def post_add_book_chapter(
    book_id: uuid.UUID,
    title: str = Form(...),
    test_count: int = Form(...),
    description: Optional[str] = Form(None),
    display_order: int = Form(1),
    db: Session = Depends(get_db),
):
    try:
        create_book_chapter(
            db=db,
            book_id=book_id,
            title=title,
            test_count=test_count,
            description=description,
            display_order=display_order,
        )
        return RedirectResponse(
            url=f"/tutor/books/{book_id}?msg=Chapter added successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/tutor/books/{book_id}?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/chapters/{chapter_id}/edit")
def post_edit_book_chapter(
    chapter_id: uuid.UUID,
    book_id: uuid.UUID = Form(...),
    title: str = Form(...),
    test_count: int = Form(...),
    description: Optional[str] = Form(None),
    display_order: int = Form(1),
    db: Session = Depends(get_db),
):
    try:
        update_book_chapter(
            db=db,
            chapter_id=chapter_id,
            title=title,
            test_count=test_count,
            description=description,
            display_order=display_order,
        )
        return RedirectResponse(
            url=f"/tutor/books/{book_id}?msg=Chapter updated successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/tutor/books/{book_id}?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/chapters/{chapter_id}/delete")
def post_delete_book_chapter(
    chapter_id: uuid.UUID,
    book_id: uuid.UUID = Form(...),
    db: Session = Depends(get_db),
):
    try:
        delete_book_chapter(db, chapter_id)
        return RedirectResponse(
            url=f"/tutor/books/{book_id}?msg=Chapter deleted successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/tutor/books/{book_id}?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

