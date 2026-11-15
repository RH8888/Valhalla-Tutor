import uuid
from datetime import date
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.timezone import today_local
from app.core.dependencies import get_current_session, get_current_user, require_tutor, verify_csrf_token
from app.core.storage import (
    REPORT_CARD_ALLOWED_EXTENSIONS,
    REPORT_CARD_ALLOWED_MIMES,
    REPORT_CARD_MAX_SIZE_BYTES,
    get_absolute_file_path,
    save_uploaded_file,
)
from app.core.templates import templates
from app.models.session import UserSession
from app.models.user import User
from app.services.academic_service import list_subjects, list_tracks
from app.services.exam_service import (
    ExamValidationError,
    create_historical_exam_result,
    get_historical_exam_result_by_id,
    list_historical_exam_results,
)
from app.services.user_service import list_students

router = APIRouter(
    prefix="/tutor/historical-exams",
    tags=["tutor-historical-exams"],
    dependencies=[Depends(require_tutor), Depends(verify_csrf_token)],
)


@router.get("", response_class=HTMLResponse)
def get_historical_exams_list(
    request: Request,
    student_id: Optional[uuid.UUID] = None,
    msg: Optional[str] = None,
    err: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    results = list_historical_exam_results(db, student_id=student_id)
    students = list_students(db)
    return templates.TemplateResponse(
        request=request,
        name="tutor/historical_exams/list.html",
        context={
            "results": results,
            "students": students,
            "selected_student_id": student_id,
            "msg": msg,
            "err": err,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.get("/{result_id}/download-report-card")
def download_historical_report_card(
    result_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    res = get_historical_exam_result_by_id(db, result_id)
    if not res:
        raise HTTPException(status_code=404, detail="Historical exam record not found.")

    if not res.report_card_file_path:
        raise HTTPException(status_code=404, detail="No report card attachment for this exam.")

    abs_path = get_absolute_file_path(res.report_card_file_path)
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="Report card file not found on disk.")

    return FileResponse(
        path=str(abs_path),
        filename=res.report_card_file_name or "report_card.pdf",
    )


@router.get("/create", response_class=HTMLResponse)
def get_create_historical_exam_form(
    request: Request,
    student_id: Optional[uuid.UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    students = list_students(db)
    tracks = list_tracks(db)
    subjects = list_subjects(db)
    return templates.TemplateResponse(
        request=request,
        name="tutor/historical_exams/create.html",
        context={
            "students": students,
            "tracks": tracks,
            "subjects": subjects,
            "selected_student_id": student_id,
            "today_date": today_local(getattr(current_user, "timezone", None)).isoformat(),
            "error": None,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("/create")
async def post_create_historical_exam(
    request: Request,
    student_id: uuid.UUID = Form(...),
    exam_name: str = Form(...),
    exam_date: str = Form(...),
    grade: Optional[str] = Form(None),
    academic_track_id: Optional[uuid.UUID] = Form(None),
    overall_rank: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    report_card_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    form_data = await request.form()
    parsed_date = date.fromisoformat(exam_date)

    # Collect subject scores from form fields: sub_{id}_name and sub_{id}_pct
    subject_scores = []
    for key, val in form_data.items():
        if key.startswith("sub_pct_") and val:
            sub_id = key.replace("sub_pct_", "")
            sub_name = form_data.get(f"sub_name_{sub_id}")
            if sub_name:
                subject_scores.append({
                    "subject_name": str(sub_name),
                    "percentage": float(val),
                })

    file_path = None
    file_name = None
    if report_card_file and report_card_file.filename:
        file_path, file_name = save_uploaded_file(
            file=report_card_file,
            subfolder="report_cards",
            allowed_exts=REPORT_CARD_ALLOWED_EXTENSIONS,
            allowed_mimes=REPORT_CARD_ALLOWED_MIMES,
            max_size=REPORT_CARD_MAX_SIZE_BYTES,
        )

    try:
        rank_val = int(overall_rank) if overall_rank and str(overall_rank).strip() else None
        create_historical_exam_result(
            db=db,
            student_id=student_id,
            exam_name=exam_name,
            exam_date=parsed_date,
            subject_scores=subject_scores,
            grade=grade,
            academic_track_id=academic_track_id,
            overall_rank=rank_val,
            notes=notes,
            report_card_file_path=file_path,
            report_card_file_name=file_name,
        )
        return RedirectResponse(
            url=f"/tutor/historical-exams?student_id={student_id}&msg=Historical exam result recorded successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except (ExamValidationError, HTTPException) as exc:
        students = list_students(db)
        tracks = list_tracks(db)
        subjects = list_subjects(db)
        detail_msg = exc.detail if hasattr(exc, "detail") else str(exc)
        return templates.TemplateResponse(
            request=request,
            name="tutor/historical_exams/create.html",
            context={
                "students": students,
                "tracks": tracks,
                "subjects": subjects,
                "selected_student_id": student_id,
                "today_date": exam_date,
                "error": detail_msg,
                "current_user": current_user,
                "current_session": current_session,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
