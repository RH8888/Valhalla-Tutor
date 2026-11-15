import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Form, File, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_session, get_current_user, require_tutor, verify_csrf_token
from app.core.storage import (
    BOOKLET_ALLOWED_EXTENSIONS,
    BOOKLET_ALLOWED_MIMES,
    BOOKLET_MAX_SIZE_BYTES,
    get_absolute_file_path,
    save_uploaded_file,
)
from app.core.templates import templates
from app.models.session import UserSession
from app.models.user import User
from app.services.academic_service import list_tracks
from app.services.practice_exam_service import (
    PracticeExamNotFoundError,
    PracticeExamValidationError,
    add_practice_exam_booklet,
    assign_practice_exam_to_students,
    configure_practice_exam_questions,
    create_practice_exam,
    create_practice_reporting_group,
    get_practice_exam_by_id,
    get_practice_exam_detailed_results,
    list_practice_exams,
)
from app.services.user_service import list_students

router = APIRouter(
    prefix="/tutor/practice-exams",
    tags=["tutor-practice-exams"],
    dependencies=[Depends(require_tutor), Depends(verify_csrf_token)],
)


@router.get("", response_class=HTMLResponse)
def get_tutor_practice_exams(
    request: Request,
    grade: Optional[str] = None,
    track_id: Optional[uuid.UUID] = None,
    msg: Optional[str] = None,
    err: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    exams = list_practice_exams(db, grade=grade, track_id=track_id)
    tracks = list_tracks(db)
    return templates.TemplateResponse(
        request=request,
        name="tutor/practice_exams/list.html",
        context={
            "exams": exams,
            "tracks": tracks,
            "selected_grade": grade,
            "selected_track_id": track_id,
            "msg": msg,
            "err": err,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.get("/create", response_class=HTMLResponse)
def get_create_practice_exam_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    tracks = list_tracks(db)
    return templates.TemplateResponse(
        request=request,
        name="tutor/practice_exams/create.html",
        context={
            "tracks": tracks,
            "error": None,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("/create")
def post_create_practice_exam(
    request: Request,
    title: str = Form(...),
    grade: str = Form(...),
    academic_track_id: uuid.UUID = Form(...),
    description: Optional[str] = Form(None),
    is_timed: bool = Form(True),
    allow_retake: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    try:
        exam = create_practice_exam(
            db,
            title=title,
            grade=grade,
            academic_track_id=academic_track_id,
            description=description,
            is_timed=is_timed,
            allow_retake=allow_retake,
        )
        return RedirectResponse(
            url=f"/tutor/practice-exams/{exam.id}?msg=Practice exam created. Now upload PDF booklets and configure questions.",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except PracticeExamValidationError as exc:
        tracks = list_tracks(db)
        return templates.TemplateResponse(
            request=request,
            name="tutor/practice_exams/create.html",
            context={
                "tracks": tracks,
                "error": str(exc),
                "title": title,
                "grade": grade,
                "current_user": current_user,
                "current_session": current_session,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )


@router.get("/{exam_id}", response_class=HTMLResponse)
def get_practice_exam_detail(
    request: Request,
    exam_id: uuid.UUID,
    msg: Optional[str] = None,
    err: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    exam = get_practice_exam_by_id(db, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Practice exam not found.")

    all_students = list_students(db)
    eligible_students = [
        s for s in all_students
        if s.grade == exam.grade and s.academic_track_id == exam.academic_track_id
    ]

    max_q = max((b.question_end for b in exam.booklets), default=0)
    q_map = {q.question_number: q for q in exam.questions}

    return templates.TemplateResponse(
        request=request,
        name="tutor/practice_exams/detail.html",
        context={
            "exam": exam,
            "max_q": max_q,
            "q_map": q_map,
            "eligible_students": eligible_students,
            "all_students": all_students,
            "msg": msg,
            "err": err,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("/{exam_id}/booklets")
async def post_upload_booklet(
    request: Request,
    exam_id: uuid.UUID,
    title: str = Form(...),
    question_start: int = Form(...),
    question_end: int = Form(...),
    duration_minutes: Optional[int] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    exam = get_practice_exam_by_id(db, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Practice exam not found.")

    try:
        rel_path, orig_name = save_uploaded_file(
            file=file,
            subfolder="practice_booklets",
            allowed_exts=BOOKLET_ALLOWED_EXTENSIONS,
            allowed_mimes=BOOKLET_ALLOWED_MIMES,
            max_size=BOOKLET_MAX_SIZE_BYTES,
        )
        add_practice_exam_booklet(
            db=db,
            practice_exam_id=exam.id,
            title=title,
            pdf_file_path=rel_path,
            pdf_file_name=orig_name,
            question_start=question_start,
            question_end=question_end,
            duration_minutes=duration_minutes,
        )
        return RedirectResponse(
            url=f"/tutor/practice-exams/{exam.id}?msg=PDF booklet '{title}' uploaded successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except (HTTPException, PracticeExamValidationError) as exc:
        detail_msg = exc.detail if hasattr(exc, "detail") else str(exc)
        return RedirectResponse(
            url=f"/tutor/practice-exams/{exam.id}?err={detail_msg}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.get("/{exam_id}/download-booklet/{booklet_id}")
def download_practice_booklet(
    exam_id: uuid.UUID,
    booklet_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    exam = get_practice_exam_by_id(db, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Practice exam not found.")

    booklet = next((b for b in exam.booklets if b.id == booklet_id), None)
    if not booklet:
        raise HTTPException(status_code=404, detail="Booklet not found.")

    abs_path = get_absolute_file_path(booklet.pdf_file_path)
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="Booklet PDF file not found on disk.")

    return FileResponse(
        path=str(abs_path),
        filename=booklet.pdf_file_name,
        media_type="application/pdf",
    )


@router.post("/{exam_id}/reporting-groups")
def post_create_reporting_group(
    exam_id: uuid.UUID,
    title: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    try:
        create_practice_reporting_group(db, exam_id, title)
        return RedirectResponse(
            url=f"/tutor/practice-exams/{exam_id}?msg=Reporting group '{title}' created",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except (PracticeExamValidationError, PracticeExamNotFoundError) as exc:
        return RedirectResponse(
            url=f"/tutor/practice-exams/{exam_id}?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/{exam_id}/questions")
async def post_configure_questions(
    request: Request,
    exam_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    form_data = await request.form()
    exam = get_practice_exam_by_id(db, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Practice exam not found.")

    # Parse questions from form: q_{q_num}_choice, q_{q_num}_subject, q_{q_num}_group
    total_q_max = max((b.question_end for b in exam.booklets), default=0)
    q_defs = []
    missing_subject = []
    missing_choice = []

    for q_num in range(1, total_q_max + 1):
        choice_val = form_data.get(f"q_{q_num}_choice")
        subj_val = form_data.get(f"q_{q_num}_subject")
        group_val = form_data.get(f"q_{q_num}_group")

        has_choice = bool(choice_val and str(choice_val).strip())
        has_subject = bool(subj_val and str(subj_val).strip())

        if has_choice and has_subject:
            q_defs.append({
                "question_number": q_num,
                "correct_choice": int(choice_val),
                "subject_id": uuid.UUID(str(subj_val)),
                "reporting_group_id": uuid.UUID(str(group_val)) if group_val and str(group_val).strip() else None,
            })
        elif has_choice and not has_subject:
            missing_subject.append(q_num)
        elif has_subject and not has_choice:
            missing_choice.append(q_num)

    try:
        if missing_subject:
            q_list = ", ".join(f"#{q}" for q in missing_subject[:5])
            more = f" and {len(missing_subject) - 5} more" if len(missing_subject) > 5 else ""
            raise PracticeExamValidationError(f"Question {q_list}{more} has an answer key selected, but no subject was chosen.")
        if missing_choice:
            q_list = ", ".join(f"#{q}" for q in missing_choice[:5])
            more = f" and {len(missing_choice) - 5} more" if len(missing_choice) > 5 else ""
            raise PracticeExamValidationError(f"Question {q_list}{more} has a subject selected, but no answer key (1, 2, 3, or 4) was selected.")
        if not q_defs:
            raise PracticeExamValidationError("No question configurations received. Please select the correct choice (1–4) and subject for each question in the Answer Keys section below.")

        configure_practice_exam_questions(db, exam_id, q_defs)
        return RedirectResponse(
            url=f"/tutor/practice-exams/{exam_id}?msg=Configured answer keys and scoring for {len(q_defs)} questions",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except PracticeExamValidationError as exc:
        return RedirectResponse(
            url=f"/tutor/practice-exams/{exam_id}?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/{exam_id}/assign")
async def post_assign_practice_exam(
    request: Request,
    exam_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    form_data = await request.form()
    student_ids_raw = form_data.getlist("student_ids")
    student_ids = [uuid.UUID(str(sid)) for sid in student_ids_raw if sid]

    try:
        assign_practice_exam_to_students(db, exam_id, student_ids)
        return RedirectResponse(
            url=f"/tutor/practice-exams/{exam_id}?msg=Assigned exam to {len(student_ids)} student(s)",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except PracticeExamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/attempts/{attempt_id}", response_class=HTMLResponse)
def get_practice_attempt_results(
    request: Request,
    attempt_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    data = get_practice_exam_detailed_results(db, attempt_id)
    return templates.TemplateResponse(
        request=request,
        name="tutor/practice_exams/attempt_result.html",
        context={
            "data": data,
            "attempt": data["attempt"],
            "exam": data["exam"],
            "current_user": current_user,
            "current_session": current_session,
        },
    )
