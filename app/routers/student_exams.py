import json
import uuid
from datetime import timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.dependencies import get_current_session, get_current_user, require_student, verify_csrf_token
from app.core.timezone import now_utc
from app.models.practice_exam import StudentPracticeAttempt
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
from app.services.academic_service import get_student_effective_subjects
from app.services.exam_service import (
    DuplicateExamResultError,
    ExamNotFoundError,
    ExamResultNotFoundError,
    ExamSessionNotFoundError,
    ExamValidationError,
    get_exam_session_by_id,
    get_student_available_exams,
    get_student_exam_analytics,
    get_student_exam_result,
    get_student_exam_result_by_id,
    get_student_series_grade_track_config,
    submit_student_exam_result,
    update_student_exam_result,
)

router = APIRouter(
    prefix="/student/exams",
    tags=["student-exams"],
    dependencies=[Depends(require_student), Depends(verify_csrf_token)],
)


def _cleanup_uploaded_file(rel_path: Optional[str]) -> None:
    if not rel_path:
        return
    try:
        abs_path = get_absolute_file_path(rel_path)
        if abs_path.exists() and abs_path.is_file():
            abs_path.unlink()
    except (OSError, ValueError):
        pass


@router.get("", response_class=HTMLResponse)
def get_student_exams_page(
    request: Request,
    msg: Optional[str] = None,
    err: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    exams_data = get_student_available_exams(db, current_user)
    practice_history = (
        db.query(StudentPracticeAttempt)
        .options(joinedload(StudentPracticeAttempt.practice_exam))
        .filter(
            StudentPracticeAttempt.student_id == current_user.id,
            StudentPracticeAttempt.status == "COMPLETED",
        )
        .order_by(desc(StudentPracticeAttempt.completed_at))
        .all()
    )
    return templates.TemplateResponse(
        request=request,
        name="student/exams/list.html",
        context={
            "upcoming": exams_data["upcoming"],
            "past": exams_data["past"],
            "practice_history": practice_history,
            "track_assigned": exams_data["track_assigned"],
            "msg": msg,
            "err": err,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.get("/{session_id}/submit", response_class=HTMLResponse)
def get_submit_result_form(
    request: Request,
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    session = get_exam_session_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Exam session not found")

    existing_result = get_student_exam_result(db, current_user.id, session_id)
    if existing_result:
        return RedirectResponse(
            url=f"/student/exams/results/{existing_result.id}/edit",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    track_config = next(
        (tc for tc in session.track_configs if tc.track_id == current_user.academic_track_id),
        None,
    )
    grade_track_cfg = get_student_series_grade_track_config(db, session.exam_id, current_user)
    if not track_config and not grade_track_cfg:
        raise HTTPException(status_code=403, detail="Exam not available for your track.")

    effective_subjects = get_student_effective_subjects(current_user)
    effective_ids = {s.id for s in effective_subjects}
    subjects = [sc.subject for sc in track_config.subject_configs if sc.subject_id in effective_ids] if track_config else []
    reporting_groups = grade_track_cfg.reporting_groups if grade_track_cfg else []

    return templates.TemplateResponse(
        request=request,
        name="student/exams/submit.html",
        context={
            "session": session,
            "subjects": subjects,
            "reporting_groups": reporting_groups,
            "error": None,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("/{session_id}/submit")
async def post_submit_result(
    request: Request,
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    session = get_exam_session_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Exam session not found")

    form_data = await request.form()
    overall_rank_raw = form_data.get("overall_rank")
    notes = form_data.get("notes")

    track_config = next(
        (tc for tc in session.track_configs if tc.track_id == current_user.academic_track_id),
        None,
    )

    grade_track_cfg = get_student_series_grade_track_config(db, session.exam_id, current_user)
    reporting_groups = grade_track_cfg.reporting_groups if grade_track_cfg else []

    rc_path: Optional[str] = None
    rc_name: Optional[str] = None
    try:
        if session.exam.is_archived or not session.exam.is_active:
            raise ExamValidationError("Cannot submit results for an archived or inactive exam series.")
        if not track_config and not grade_track_cfg:
            raise ExamValidationError("You are not configured or eligible for this exam.")

        group_data = []
        if reporting_groups:
            for grp in reporting_groups:
                pct_val = form_data.get(f"group_{grp.id}_percentage")
                if pct_val is not None and str(pct_val).strip():
                    sub_names = "، ".join(s.name for s in grp.subjects) if grp.subjects else grp.title
                    group_data.append({
                        "reporting_group_id": grp.id,
                        "group_title": grp.title,
                        "percentage": float(pct_val),
                        "included_subject_names": sub_names,
                    })

        subject_data = []
        if track_config:
            for sc in track_config.subject_configs:
                sub_id = sc.subject_id
                corr_val = form_data.get(f"correct_{sub_id}")
                incorr_val = form_data.get(f"incorrect_{sub_id}")
                pct_val = form_data.get(f"percentage_{sub_id}")
                if corr_val is not None and pct_val is not None:
                    subject_data.append({
                        "subject_id": sub_id,
                        "correct_answers": corr_val,
                        "incorrect_answers": incorr_val or 0,
                        "percentage": pct_val,
                    })

        rank_val = int(overall_rank_raw) if overall_rank_raw and str(overall_rank_raw).strip() else None

        report_card_file = form_data.get("report_card_file")
        if isinstance(report_card_file, UploadFile) and report_card_file.filename:
            rc_path, rc_name = save_uploaded_file(
                file=report_card_file,
                subfolder="report_cards",
                allowed_exts=REPORT_CARD_ALLOWED_EXTENSIONS,
                allowed_mimes=REPORT_CARD_ALLOWED_MIMES,
                max_size=REPORT_CARD_MAX_SIZE_BYTES,
            )

        submit_student_exam_result(
            db,
            student=current_user,
            exam_session_id=session_id,
            subject_data=subject_data if subject_data else None,
            group_data=group_data if group_data else None,
            overall_rank=rank_val,
            notes=str(notes) if notes else None,
            report_card_file_path=rc_path,
            report_card_file_name=rc_name,
        )
        return RedirectResponse(
            url="/student/exams?msg=Exam results submitted successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except (ValueError, ExamValidationError, DuplicateExamResultError, HTTPException) as exc:
        _cleanup_uploaded_file(rc_path)
        detail_msg = exc.detail if isinstance(exc, HTTPException) else str(exc)
        if isinstance(exc, ValueError):
            detail_msg = "Please enter valid numeric scores and rank values."
        effective_subjects = get_student_effective_subjects(current_user)
        effective_ids = {s.id for s in effective_subjects}
        subjects = [sc.subject for sc in track_config.subject_configs if sc.subject_id in effective_ids] if track_config else []
        return templates.TemplateResponse(
            request=request,
            name="student/exams/submit.html",
            context={
                "session": session,
                "subjects": subjects,
                "reporting_groups": reporting_groups,
                "error": detail_msg,
                "current_user": current_user,
                "current_session": current_session,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        _cleanup_uploaded_file(rc_path)
        raise


@router.get("/results/{result_id}/edit", response_class=HTMLResponse)
def get_edit_result_form(
    request: Request,
    result_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    result = get_student_exam_result_by_id(db, result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    if result.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this result")
    if result.is_reviewed or getattr(result, "is_tutor_corrected", False):
        raise HTTPException(status_code=400, detail="Cannot edit an exam result that has been reviewed or corrected by a tutor.")

    session = result.exam_session
    if session:
        if session.status in ("SKIPPED", "CANCELLED"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot edit results for a skipped or cancelled exam occurrence.",
            )
        now = now_utc()
        s_deadline = session.submission_deadline
        if s_deadline and s_deadline.tzinfo is None:
            s_deadline = s_deadline.replace(tzinfo=timezone.utc)
        if s_deadline and now > s_deadline:
            if not getattr(session, "allow_late_submission", True):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Submission deadline has passed for this exam occurrence.",
                )

    sub_res_map = {sr.subject_id: sr for sr in result.subject_results}
    track_config = next(
        (tc for tc in result.exam_session.track_configs if tc.track_id == current_user.academic_track_id),
        None,
    )
    subjects = [sc.subject for sc in track_config.subject_configs] if track_config else []

    return templates.TemplateResponse(
        request=request,
        name="student/exams/edit.html",
        context={
            "result": result,
            "session": result.exam_session,
            "group_results": result.group_results,
            "subjects": subjects,
            "sub_res_map": sub_res_map,
            "error": None,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("/results/{result_id}/edit")
async def post_edit_result(
    request: Request,
    result_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    result = get_student_exam_result_by_id(db, result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    if result.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this result")
    if result.is_reviewed or getattr(result, "is_tutor_corrected", False):
        raise HTTPException(status_code=400, detail="Cannot edit an exam result that has been reviewed or corrected by a tutor.")

    session = result.exam_session
    if session:
        if session.status in ("SKIPPED", "CANCELLED"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot edit results for a skipped or cancelled exam occurrence.",
            )
        now = now_utc()
        s_deadline = session.submission_deadline
        if s_deadline and s_deadline.tzinfo is None:
            s_deadline = s_deadline.replace(tzinfo=timezone.utc)
        if s_deadline and now > s_deadline:
            if not getattr(session, "allow_late_submission", True):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Submission deadline has passed for this exam occurrence.",
                )

    form_data = await request.form()
    overall_rank_raw = form_data.get("overall_rank")
    notes = form_data.get("notes")

    track_config = next(
        (tc for tc in result.exam_session.track_configs if tc.track_id == current_user.academic_track_id),
        None,
    )

    old_rc_path = result.report_card_file_path
    rc_path: Optional[str] = None
    rc_name: Optional[str] = None
    try:
        if session and session.exam and (session.exam.is_archived or not session.exam.is_active):
            raise ExamValidationError("Cannot edit results for an archived or inactive exam series.")

        # If result has group_results, parse group_data
        group_data = []
        if result.group_results:
            for gr in result.group_results:
                key = gr.reporting_group_id or gr.id
                pct_val = form_data.get(f"group_{key}_percentage")
                if pct_val is None:
                    pct_val = form_data.get(f"group_{gr.id}_percentage")
                if pct_val is not None and str(pct_val).strip():
                    group_data.append({
                        "reporting_group_id": gr.reporting_group_id,
                        "group_title": gr.group_title,
                        "percentage": float(pct_val),
                        "included_subject_names": gr.included_subject_names,
                    })

        subject_data = []
        if track_config and not group_data:
            for sc in track_config.subject_configs:
                sub_id = sc.subject_id
                corr_val = form_data.get(f"correct_{sub_id}")
                incorr_val = form_data.get(f"incorrect_{sub_id}")
                pct_val = form_data.get(f"percentage_{sub_id}")
                if corr_val is not None and pct_val is not None:
                    subject_data.append({
                        "subject_id": sub_id,
                        "correct_answers": corr_val,
                        "incorrect_answers": incorr_val or 0,
                        "percentage": pct_val,
                    })

        rank_val = int(overall_rank_raw) if overall_rank_raw and str(overall_rank_raw).strip() else None

        report_card_file = form_data.get("report_card_file")
        if isinstance(report_card_file, UploadFile) and report_card_file.filename:
            rc_path, rc_name = save_uploaded_file(
                file=report_card_file,
                subfolder="report_cards",
                allowed_exts=REPORT_CARD_ALLOWED_EXTENSIONS,
                allowed_mimes=REPORT_CARD_ALLOWED_MIMES,
                max_size=REPORT_CARD_MAX_SIZE_BYTES,
            )

        update_student_exam_result(
            db,
            student=current_user,
            result_id=result_id,
            subject_data=subject_data if subject_data else None,
            group_data=group_data if group_data else None,
            overall_rank=rank_val,
            notes=str(notes) if notes else None,
            report_card_file_path=rc_path,
            report_card_file_name=rc_name,
        )
        if rc_path and old_rc_path and old_rc_path != rc_path:
            _cleanup_uploaded_file(old_rc_path)
        return RedirectResponse(
            url="/student/exams?msg=Exam results updated successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except (ValueError, ExamValidationError, ExamResultNotFoundError, HTTPException) as exc:
        _cleanup_uploaded_file(rc_path)
        detail_msg = exc.detail if isinstance(exc, HTTPException) else str(exc)
        if isinstance(exc, ValueError):
            detail_msg = "Please enter valid numeric scores and rank values."
        sub_res_map = {sr.subject_id: sr for sr in result.subject_results}
        subjects = [sc.subject for sc in track_config.subject_configs] if track_config else []
        return templates.TemplateResponse(
            request=request,
            name="student/exams/edit.html",
            context={
                "result": result,
                "session": result.exam_session,
                "group_results": result.group_results,
                "subjects": subjects,
                "sub_res_map": sub_res_map,
                "error": detail_msg,
                "current_user": current_user,
                "current_session": current_session,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        _cleanup_uploaded_file(rc_path)
        raise


@router.get("/analytics", response_class=HTMLResponse)
def get_student_analytics_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    analytics = get_student_exam_analytics(db, current_user.id)
    return templates.TemplateResponse(
        request=request,
        name="student/exams/analytics.html",
        context={
            "analytics": analytics,
            "analytics_json": json.dumps(analytics),
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.get("/results/{result_id}/report-card")
def download_student_exam_report_card(
    result_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = get_student_exam_result_by_id(db, result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found.")
    if result.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="Unauthorized access to this report card.")
    if not result.report_card_file_path:
        raise HTTPException(status_code=404, detail="No report card attachment uploaded.")

    abs_path = get_absolute_file_path(result.report_card_file_path)
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="Report card file not found on disk.")

    return FileResponse(
        path=str(abs_path),
        filename=result.report_card_file_name or "report_card.pdf",
    )
