import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_session, get_current_user, require_student, verify_csrf_token
from app.core.storage import get_absolute_file_path
from app.core.templates import templates
from app.models.session import UserSession
from app.models.user import User
from app.services.exam_service import (
    get_historical_exam_result_by_id,
    list_historical_exam_results,
)

router = APIRouter(
    prefix="/student/historical-exams",
    tags=["student-historical-exams"],
    dependencies=[Depends(require_student), Depends(verify_csrf_token)],
)


@router.get("", response_class=HTMLResponse)
def get_student_historical_exams(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    results = list_historical_exam_results(db, student_id=current_user.id)
    return templates.TemplateResponse(
        request=request,
        name="student/historical_exams/list.html",
        context={
            "results": results,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.get("/{result_id}/download-report-card")
def download_student_report_card(
    result_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    res = get_historical_exam_result_by_id(db, result_id)
    if not res:
        raise HTTPException(status_code=404, detail="Historical exam record not found.")

    if res.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="Unauthorized access to this report card.")

    if not res.report_card_file_path:
        raise HTTPException(status_code=404, detail="No report card attachment for this exam.")

    abs_path = get_absolute_file_path(res.report_card_file_path)
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="Report card file not found on disk.")

    return FileResponse(
        path=str(abs_path),
        filename=res.report_card_file_name or "report_card.pdf",
    )

