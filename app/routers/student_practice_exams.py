import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_session, get_current_user, require_student, verify_csrf_token
from app.core.storage import get_absolute_file_path
from app.core.templates import templates
from app.models.practice_exam import PracticeExamBooklet, StudentPracticeAttempt
from app.models.session import UserSession
from app.models.user import User
from app.services.practice_exam_service import (
    PracticeExamLockedError,
    PracticeExamNotFoundError,
    PracticeExamValidationError,
    get_practice_exam_by_id,
    get_practice_exam_detailed_results,
    get_student_available_practice_exams,
    get_student_booklet_state,
    save_student_answer,
    start_practice_attempt,
    submit_booklet_answers,
)

router = APIRouter(
    prefix="/student/practice-exams",
    tags=["student-practice-exams"],
    dependencies=[Depends(require_student), Depends(verify_csrf_token)],
)


@router.get("", response_class=HTMLResponse)
def get_student_practice_exams(
    request: Request,
    msg: Optional[str] = None,
    err: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    exams = get_student_available_practice_exams(db, current_user)
    return templates.TemplateResponse(
        request=request,
        name="student/practice_exams/list.html",
        context={
            "exams": exams,
            "msg": msg,
            "err": err,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("/{exam_id}/start")
def post_start_practice_exam(
    exam_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    try:
        attempt = start_practice_attempt(db, current_user, exam_id)
        # Find active booklet attempt
        active_b_attempt = next((ba for ba in attempt.booklet_attempts if not ba.is_locked), None)
        if not active_b_attempt:
            active_b_attempt = attempt.booklet_attempts[-1]

        return RedirectResponse(
            url=f"/student/practice-exams/attempts/{attempt.id}/booklets/{active_b_attempt.booklet_id}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except (PracticeExamValidationError, PracticeExamNotFoundError) as exc:
        return RedirectResponse(
            url=f"/student/practice-exams?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.get("/booklets/{booklet_id}/download")
def download_student_practice_booklet(
    booklet_id: uuid.UUID,
    attempt_id: Optional[uuid.UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booklet = db.query(PracticeExamBooklet).filter(PracticeExamBooklet.id == booklet_id).first()
    if not booklet:
        raise HTTPException(status_code=404, detail="Booklet not found.")

    # 1. Authorization: check student assignment/eligibility for booklet's practice exam
    exam = booklet.practice_exam
    has_direct_assignment = any(a.student_id == current_user.id for a in exam.assignments)
    is_eligible = current_user.grade == exam.grade and current_user.academic_track_id == exam.academic_track_id
    if not (has_direct_assignment or is_eligible):
        raise HTTPException(status_code=403, detail="You are not authorized to download this booklet.")

    # 2. Check active attempt and enforce access isolation
    if attempt_id:
        attempt = db.query(StudentPracticeAttempt).filter(StudentPracticeAttempt.id == attempt_id).first()
        if not attempt:
            raise HTTPException(status_code=404, detail="Attempt not found.")
        if attempt.student_id != current_user.id:
            raise HTTPException(status_code=403, detail="Unauthorized access to another student's attempt.")
        if attempt.practice_exam_id != exam.id:
            raise HTTPException(status_code=403, detail="Attempt does not belong to this practice exam.")
        if attempt.status != "IN_PROGRESS":
            raise HTTPException(status_code=403, detail="Exam attempt is not active.")
    else:
        attempt = (
            db.query(StudentPracticeAttempt)
            .filter(
                StudentPracticeAttempt.student_id == current_user.id,
                StudentPracticeAttempt.practice_exam_id == exam.id,
                StudentPracticeAttempt.status == "IN_PROGRESS",
            )
            .order_by(StudentPracticeAttempt.started_at.desc())
            .first()
        )
        if not attempt:
            raise HTTPException(status_code=403, detail="Active exam attempt required to download booklet.")

    # 3. Check that the requested booklet is unlocked for that attempt
    try:
        state = get_student_booklet_state(db, attempt.id, booklet.id)
    except PracticeExamNotFoundError:
        raise HTTPException(status_code=404, detail="Booklet or attempt not found.")

    b_attempt = state.get("booklet_attempt")
    if not b_attempt:
        raise HTTPException(status_code=403, detail="Booklet is not unlocked for this attempt.")
    if state.get("is_locked"):
        raise HTTPException(status_code=403, detail="Booklet is locked.")

    abs_path = get_absolute_file_path(booklet.pdf_file_path)
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="Booklet file not found on disk.")

    return FileResponse(
        path=str(abs_path),
        filename=booklet.pdf_file_name,
        media_type="application/pdf",
    )


@router.get("/attempts/{attempt_id}/booklets/{booklet_id}/download")
def download_student_practice_booklet_with_attempt(
    attempt_id: uuid.UUID,
    booklet_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return download_student_practice_booklet(
        booklet_id=booklet_id,
        attempt_id=attempt_id,
        db=db,
        current_user=current_user,
    )


@router.get("/attempts/{attempt_id}/booklets/{booklet_id}", response_class=HTMLResponse)
def get_booklet_runner(
    request: Request,
    attempt_id: uuid.UUID,
    booklet_id: uuid.UUID,
    msg: Optional[str] = None,
    err: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    try:
        state = get_student_booklet_state(db, attempt_id, booklet_id)
        attempt = state["attempt"]
        if attempt.student_id != current_user.id:
            raise HTTPException(status_code=403, detail="Unauthorized access to this attempt.")

        # 1. If attempt is completed, redirect to results page
        if attempt.status == "COMPLETED":
            return RedirectResponse(
                url=f"/student/practice-exams/attempts/{attempt_id}/results",
                status_code=status.HTTP_303_SEE_OTHER,
            )

        # 2. Check if student attempted to access a future booklet directly
        b_attempt = state["booklet_attempt"]
        if not b_attempt:
            active_ba = next((ba for ba in attempt.booklet_attempts if not ba.is_locked), None)
            if active_ba:
                return RedirectResponse(
                    url=f"/student/practice-exams/attempts/{attempt_id}/booklets/{active_ba.booklet_id}?err=Booklet is not unlocked yet.",
                    status_code=status.HTTP_303_SEE_OTHER,
                )
            if attempt.booklet_attempts:
                latest_ba = attempt.booklet_attempts[-1]
                return RedirectResponse(
                    url=f"/student/practice-exams/attempts/{attempt_id}/booklets/{latest_ba.booklet_id}",
                    status_code=status.HTTP_303_SEE_OTHER,
                )
            raise HTTPException(status_code=403, detail="Booklet is not unlocked for this attempt.")

        # 3. Server-side expiration / progression check:
        # If this booklet is locked or expired, automatically advance to next booklet or finalize attempt
        if state["is_locked"]:
            res = submit_booklet_answers(
                db=db,
                student=current_user,
                attempt_id=attempt_id,
                booklet_id=booklet_id,
                answers={},
                advance_to_next=True,
            )
            if res.get("completed"):
                return RedirectResponse(
                    url=f"/student/practice-exams/attempts/{attempt_id}/results?msg=Practice exam completed! Review your results below.",
                    status_code=status.HTTP_303_SEE_OTHER,
                )
            else:
                next_id = res.get("next_booklet_id")
                return RedirectResponse(
                    url=f"/student/practice-exams/attempts/{attempt_id}/booklets/{next_id}",
                    status_code=status.HTTP_303_SEE_OTHER,
                )

        return templates.TemplateResponse(
            request=request,
            name="student/practice_exams/runner.html",
            context={
                "attempt": state["attempt"],
                "booklet": state["booklet"],
                "booklet_attempt": state["booklet_attempt"],
                "is_locked": state["is_locked"],
                "remaining_seconds": state["remaining_seconds"],
                "questions": state["questions"],
                "answers_map": state["answers_map"],
                "msg": msg,
                "err": err,
                "current_user": current_user,
                "current_session": current_session,
            },
        )
    except PracticeExamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/attempts/{attempt_id}/booklets/{booklet_id}/answers")
@router.post("/attempts/{attempt_id}/booklets/{booklet_id}/answer")
async def post_save_single_answer(
    request: Request,
    attempt_id: uuid.UUID,
    booklet_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    q_num = body.get("question_number")
    if q_num is None:
        raise HTTPException(status_code=400, detail="question_number is required.")
    try:
        q_num = int(q_num)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="question_number must be an integer.")

    choice = body.get("selected_choice")
    if choice is not None:
        try:
            choice = int(choice)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="selected_choice must be 1, 2, 3, or 4.")

    try:
        ans = save_student_answer(
            db=db,
            student=current_user,
            attempt_id=attempt_id,
            booklet_id=booklet_id,
            question_number=q_num,
            selected_choice=choice,
        )
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "question_number": ans.question_number,
                "selected_choice": ans.selected_choice,
            },
        )
    except PracticeExamLockedError as exc:
        return JSONResponse(status_code=423, content={"status": "locked", "detail": str(exc)})
    except PracticeExamValidationError as exc:
        return JSONResponse(status_code=400, content={"status": "error", "detail": str(exc)})
    except PracticeExamNotFoundError as exc:
        return JSONResponse(status_code=404, content={"status": "error", "detail": str(exc)})


@router.post("/attempts/{attempt_id}/booklets/{booklet_id}/save")
async def post_save_booklet_answers(
    request: Request,
    attempt_id: uuid.UUID,
    booklet_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body.")
        if "question_number" in body:
            return await post_save_single_answer(request, attempt_id, booklet_id, db, current_user, current_session)
        answers = {int(k): (int(v) if v is not None else None) for k, v in body.get("answers", {}).items()}
        try:
            submit_booklet_answers(db, current_user, attempt_id, booklet_id, answers, advance_to_next=False)
            return JSONResponse(status_code=200, content={"status": "ok"})
        except PracticeExamLockedError as exc:
            return JSONResponse(status_code=423, content={"status": "locked", "detail": str(exc)})
        except PracticeExamValidationError as exc:
            return JSONResponse(status_code=400, content={"status": "error", "detail": str(exc)})

    form_data = await request.form()
    state = get_student_booklet_state(db, attempt_id, booklet_id)
    questions = state["questions"]

    answers: Dict[int, Optional[int]] = {}
    for q in questions:
        val = form_data.get(f"q_{q.question_number}")
        answers[q.question_number] = int(val) if val and str(val).isdigit() else None

    try:
        submit_booklet_answers(
            db=db,
            student=current_user,
            attempt_id=attempt_id,
            booklet_id=booklet_id,
            answers=answers,
            advance_to_next=False,
        )
        return RedirectResponse(
            url=f"/student/practice-exams/attempts/{attempt_id}/booklets/{booklet_id}?msg=Answers saved",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except PracticeExamLockedError as exc:
        return RedirectResponse(
            url=f"/student/practice-exams/attempts/{attempt_id}/booklets/{booklet_id}?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.post("/attempts/{attempt_id}/booklets/{booklet_id}/submit")
async def post_submit_booklet_and_advance(
    request: Request,
    attempt_id: uuid.UUID,
    booklet_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    content_type = request.headers.get("content-type", "")
    is_json = "application/json" in content_type or request.headers.get("accept", "").startswith("application/json")
    answers: Dict[int, Optional[int]] = {}

    if "application/json" in content_type:
        try:
            body = await request.json()
            if isinstance(body, dict):
                raw_ans = body.get("answers", body)
                if isinstance(raw_ans, dict):
                    for k, v in raw_ans.items():
                        if str(k).isdigit():
                            answers[int(k)] = int(v) if v is not None and str(v).isdigit() else None
        except Exception:
            answers = {}
    else:
        form_data = await request.form()
        state = get_student_booklet_state(db, attempt_id, booklet_id)
        for q in state["questions"]:
            val = form_data.get(f"q_{q.question_number}")
            answers[q.question_number] = int(val) if val and str(val).isdigit() else None

    try:
        res = submit_booklet_answers(
            db=db,
            student=current_user,
            attempt_id=attempt_id,
            booklet_id=booklet_id,
            answers=answers,
            advance_to_next=True,
        )
        if res.get("completed"):
            redirect_url = f"/student/practice-exams/attempts/{attempt_id}/results?msg=Practice exam completed! Review your results below."
        else:
            next_id = res.get("next_booklet_id")
            redirect_url = f"/student/practice-exams/attempts/{attempt_id}/booklets/{next_id}?msg=Booklet submitted. Proceeding to next booklet."

        if is_json:
            return JSONResponse(status_code=200, content={"status": "ok", "completed": res.get("completed"), "redirect_url": redirect_url})
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)
    except PracticeExamLockedError as exc:
        if is_json:
            return JSONResponse(status_code=423, content={"status": "locked", "detail": str(exc)})
        return RedirectResponse(
            url=f"/student/practice-exams/attempts/{attempt_id}/booklets/{booklet_id}?err={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.get("/attempts/{attempt_id}/results", response_class=HTMLResponse)
def get_practice_results_page(
    request: Request,
    attempt_id: uuid.UUID,
    msg: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    try:
        data = get_practice_exam_detailed_results(db, attempt_id)
    except PracticeExamValidationError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except PracticeExamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if data["attempt"].student_id != current_user.id:
        raise HTTPException(status_code=403, detail="Unauthorized access to results.")

    return templates.TemplateResponse(
        request=request,
        name="student/practice_exams/results.html",
        context={
            "data": data,
            "attempt": data["attempt"],
            "exam": data["exam"],
            "msg": msg,
            "current_user": current_user,
            "current_session": current_session,
        },
    )
