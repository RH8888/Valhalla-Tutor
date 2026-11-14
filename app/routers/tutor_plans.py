import uuid
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
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
from app.models.book import Book, BookChapter
from app.models.course import Course, CourseChapter
from app.models.plan import PlanAssignment, PlanStatus, StudyPlan, TaskType
from app.models.session import UserSession
from app.models.subject import Subject
from app.models.user import User
from app.services.academic_service import get_student_effective_subjects
from app.services.plan_service import (
    AssignmentNotFoundError,
    PlanNotFoundError,
    PlanValidationError,
    calculate_plan_totals,
    create_assignment,
    create_study_plan,
    delete_assignment,
    delete_study_plan,
    estimate_test_duration,
    estimate_video_duration,
    format_duration_minutes,
    get_active_student_plan,
    get_assignment,
    get_study_plan,
    list_student_plans,
    publish_study_plan,
    archive_study_plan,
    reorder_assignment,
    update_assignment,
)
from app.services.resource_service import list_books, list_courses
from app.services.user_service import get_student_by_id

router = APIRouter(
    prefix="/tutor",
    tags=["tutor_plans"],
    dependencies=[Depends(require_tutor), Depends(verify_csrf_token)],
)


@router.get("/students/{student_id}/plans", response_class=HTMLResponse)
def get_student_plans_page(
    student_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    student = get_student_by_id(db, student_id)
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    plans = list_student_plans(db, student_id)
    today = date.today()
    default_start_date = today.isoformat()

    return templates.TemplateResponse(
        request=request,
        name="tutor/plans/student_plans.html",
        context={
            "student": student,
            "plans": plans,
            "default_start_date": default_start_date,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("/students/{student_id}/plans")
def post_create_plan(
    student_id: uuid.UUID,
    start_date: str = Form(...),
    title: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    student = get_student_by_id(db, student_id)
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    try:
        parsed_start = date.fromisoformat(start_date)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid start date format.")

    plan = create_study_plan(
        db=db,
        student_id=student_id,
        tutor_id=current_user.id,
        start_date=parsed_start,
        title=title,
    )
    return RedirectResponse(
        url=f"/tutor/plans/{plan.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/plans/{plan_id}", response_class=HTMLResponse)
def get_plan_view(
    plan_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    plan = get_study_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")

    student = plan.student
    effective_subjects = get_student_effective_subjects(student)
    assignments = plan.assignments

    # 14 days
    days = [plan.start_date + timedelta(days=i) for i in range(14)]
    daily_totals, subject_totals, plan_total = calculate_plan_totals(assignments, days, effective_subjects)

    # Format human-readable strings
    daily_totals_formatted = {d: format_duration_minutes(m) for d, m in daily_totals.items()}
    subject_totals_formatted = {sub_id: format_duration_minutes(m) for sub_id, m in subject_totals.items()}
    plan_total_formatted = format_duration_minutes(plan_total)

    # Group assignments by (scheduled_date, subject_id)
    assignments_by_cell: Dict[Tuple[date, uuid.UUID], List[PlanAssignment]] = {}
    for a in assignments:
        key = (a.scheduled_date, a.subject_id)
        if key not in assignments_by_cell:
            assignments_by_cell[key] = []
        assignments_by_cell[key].append(a)

    return templates.TemplateResponse(
        request=request,
        name="tutor/plans/planner.html",
        context={
            "plan": plan,
            "student": student,
            "effective_subjects": effective_subjects,
            "days": days,
            "assignments_by_cell": assignments_by_cell,
            "daily_totals": daily_totals,
            "daily_totals_formatted": daily_totals_formatted,
            "subject_totals": subject_totals,
            "subject_totals_formatted": subject_totals_formatted,
            "plan_total": plan_total,
            "plan_total_formatted": plan_total_formatted,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.get("/plans/{plan_id}/options/resources/{subject_id}", response_class=HTMLResponse)
def get_resources_for_subject(
    plan_id: uuid.UUID,
    subject_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Return JSON or HTML snippet of courses and books for a subject."""
    courses = list_courses(db, subject_id=subject_id)
    books = list_books(db, subject_id=subject_id)

    course_options = "".join([f'<option value="{c.id}">{c.teacher_name} - {c.name}</option>' for c in courses])
    book_options = "".join([f'<option value="{b.id}">{b.title} (Grade {b.grade})</option>' for b in books])

    return HTMLResponse(
        f"""
        <div id="course-options-container" hx-swap-oob="innerHTML:#course-select">
            <option value="">-- Select Course / Teacher --</option>
            {course_options}
        </div>
        <div id="book-options-container" hx-swap-oob="innerHTML:#book-select">
            <option value="">-- Select Book --</option>
            {book_options}
        </div>
        """
    )


@router.get("/plans/{plan_id}/options/course-chapters/{course_id}", response_class=HTMLResponse)
def get_chapters_for_course(
    plan_id: uuid.UUID,
    course_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        return HTMLResponse('<option value="">-- No chapters --</option>')

    options = ['<option value="">-- Select Chapter --</option>']
    for ch in course.chapters:
        options.append(f'<option value="{ch.id}" data-videos="{ch.video_count}">{ch.name} ({ch.video_count} videos)</option>')
    return HTMLResponse("".join(options))


@router.get("/plans/{plan_id}/options/book-chapters/{book_id}", response_class=HTMLResponse)
def get_chapters_for_book(
    plan_id: uuid.UUID,
    book_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        return HTMLResponse('<option value="">-- No chapters --</option>')

    options = ['<option value="">-- Select Chapter --</option>']
    for ch in book.chapters:
        options.append(f'<option value="{ch.id}" data-tests="{ch.test_count}">{ch.title} ({ch.test_count} tests)</option>')
    return HTMLResponse("".join(options))


@router.get("/plans/{plan_id}/estimate-video", response_class=HTMLResponse)
def get_video_estimate_badge(
    plan_id: uuid.UUID,
    course_id: Optional[uuid.UUID] = Query(None),
    video_count: int = Query(1),
    db: Session = Depends(get_db),
):
    plan = get_study_plan(db, plan_id)
    if not plan or not course_id:
        return HTMLResponse("")

    est = estimate_video_duration(db, plan.student_id, course_id, video_count)
    if est.is_historical and est.suggested_duration_minutes:
        return HTMLResponse(
            f"""
            <div class="mt-2 p-2.5 rounded-lg bg-indigo-50 border border-indigo-200 text-xs text-indigo-900 flex items-start space-x-2">
                <span class="text-indigo-600 font-bold">📊</span>
                <div>
                    <span class="font-semibold text-indigo-800">Historical Estimate:</span>
                    <span>{est.suggested_duration_minutes} minutes</span>
                    <p class="text-indigo-600 mt-0.5">{est.basis_text}</p>
                </div>
            </div>
            <script>
                document.getElementById('video-duration-input').value = '{est.suggested_duration_minutes}';
                document.getElementById('video-is-estimated-input').value = 'true';
                document.getElementById('video-estimated-duration-input').value = '{est.suggested_duration_minutes}';
            </script>
            """
        )
    return HTMLResponse(
        """
        <div class="mt-2 p-2 rounded-lg bg-slate-50 border border-slate-200 text-xs text-slate-600">
            <span>ℹ️ No completed video history for this course yet. Enter duration manually.</span>
        </div>
        """
    )


@router.get("/plans/{plan_id}/estimate-test", response_class=HTMLResponse)
def get_test_estimate_badge(
    plan_id: uuid.UUID,
    book_id: Optional[uuid.UUID] = Query(None),
    test_start: int = Query(1),
    test_end: int = Query(1),
    db: Session = Depends(get_db),
):
    plan = get_study_plan(db, plan_id)
    if not plan or not book_id:
        return HTMLResponse("")

    test_count = test_end - test_start + 1
    if test_count <= 0:
        return HTMLResponse('<div class="mt-2 p-2 rounded bg-amber-50 text-xs text-amber-700">Invalid test range: end test must be >= start test.</div>')

    est = estimate_test_duration(db, plan.student_id, book_id, test_count)
    if est.is_historical and est.suggested_duration_minutes:
        return HTMLResponse(
            f"""
            <div class="mt-2 p-2.5 rounded-lg bg-amber-50 border border-amber-200 text-xs text-amber-900 flex items-start space-x-2">
                <span class="text-amber-600 font-bold">📊</span>
                <div>
                    <span class="font-semibold text-amber-800">Historical Estimate:</span>
                    <span>{est.suggested_duration_minutes} minutes ({test_count} tests)</span>
                    <p class="text-amber-600 mt-0.5">{est.basis_text}</p>
                </div>
            </div>
            <script>
                document.getElementById('test-duration-input').value = '{est.suggested_duration_minutes}';
                document.getElementById('test-is-estimated-input').value = 'true';
                document.getElementById('test-estimated-duration-input').value = '{est.suggested_duration_minutes}';
            </script>
            """
        )
    return HTMLResponse(
        f"""
        <div class="mt-2 p-2 rounded-lg bg-slate-50 border border-slate-200 text-xs text-slate-600">
            <span>ℹ️ {test_count} test(s) assigned. No completed history for this book yet; enter duration manually.</span>
        </div>
        """
    )


@router.post("/plans/{plan_id}/publish")
def post_publish_plan(
    plan_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    plan = publish_study_plan(db, plan_id)
    return RedirectResponse(
        url=f"/tutor/plans/{plan.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/plans/{plan_id}/archive")
def post_archive_plan(
    plan_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    plan = archive_study_plan(db, plan_id)
    return RedirectResponse(
        url=f"/tutor/plans/{plan.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/plans/{plan_id}/delete")
def post_delete_plan(
    plan_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    plan = get_study_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")
    student_id = plan.student_id
    delete_study_plan(db, plan_id)
    return RedirectResponse(
        url=f"/tutor/students/{student_id}/plans",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/plans/{plan_id}/assignments")
def post_create_assignment(
    plan_id: uuid.UUID,
    scheduled_date: str = Form(...),
    subject_id: uuid.UUID = Form(...),
    task_type: TaskType = Form(...),
    recommended_duration_minutes: int = Form(...),
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    is_estimated: bool = Form(False),
    estimated_duration_minutes: Optional[int] = Form(None),
    # Video fields
    course_id: Optional[uuid.UUID] = Form(None),
    course_chapter_id: Optional[uuid.UUID] = Form(None),
    video_start_num: Optional[int] = Form(None),
    video_end_num: Optional[int] = Form(None),
    video_count: Optional[int] = Form(None),
    # Test fields
    book_id: Optional[uuid.UUID] = Form(None),
    book_chapter_id: Optional[uuid.UUID] = Form(None),
    test_start_num: Optional[int] = Form(None),
    test_end_num: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    parsed_date = date.fromisoformat(scheduled_date)
    try:
        create_assignment(
            db=db,
            plan_id=plan_id,
            scheduled_date=parsed_date,
            subject_id=subject_id,
            task_type=task_type,
            recommended_duration_minutes=recommended_duration_minutes,
            title=title,
            description=description,
            is_estimated=is_estimated,
            estimated_duration_minutes=estimated_duration_minutes,
            course_id=course_id,
            course_chapter_id=course_chapter_id,
            video_start_num=video_start_num,
            video_end_num=video_end_num,
            video_count=video_count,
            book_id=book_id,
            book_chapter_id=book_chapter_id,
            test_start_num=test_start_num,
            test_end_num=test_end_num,
        )
    except PlanValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return RedirectResponse(
        url=f"/tutor/plans/{plan_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/plans/assignments/{assignment_id}/edit", response_class=HTMLResponse)
def get_edit_assignment_modal(
    assignment_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_session: UserSession = Depends(get_current_session),
):
    assignment = get_assignment(db, assignment_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    plan = assignment.study_plan
    effective_subjects = get_student_effective_subjects(plan.student)
    days = [plan.start_date + timedelta(days=i) for i in range(14)]

    return templates.TemplateResponse(
        request=request,
        name="tutor/plans/edit_task_modal.html",
        context={
            "assignment": assignment,
            "plan": plan,
            "effective_subjects": effective_subjects,
            "days": days,
            "current_session": current_session,
        },
    )


@router.post("/plans/assignments/{assignment_id}/edit")
def post_edit_assignment(
    assignment_id: uuid.UUID,
    title: str = Form(...),
    recommended_duration_minutes: int = Form(...),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    assignment = get_assignment(db, assignment_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    plan_id = assignment.study_plan_id
    try:
        update_assignment(
            db=db,
            assignment_id=assignment_id,
            title=title,
            recommended_duration_minutes=recommended_duration_minutes,
            description=description,
        )
    except PlanValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return RedirectResponse(
        url=f"/tutor/plans/{plan_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/plans/assignments/{assignment_id}/move")
def post_move_assignment(
    assignment_id: uuid.UUID,
    new_date: str = Form(...),
    new_subject_id: uuid.UUID = Form(...),
    db: Session = Depends(get_db),
):
    assignment = get_assignment(db, assignment_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    plan_id = assignment.study_plan_id
    parsed_date = date.fromisoformat(new_date)
    try:
        update_assignment(
            db=db,
            assignment_id=assignment_id,
            scheduled_date=parsed_date,
            subject_id=new_subject_id,
        )
    except PlanValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return RedirectResponse(
        url=f"/tutor/plans/{plan_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/plans/assignments/{assignment_id}/reorder")
def post_reorder_assignment(
    assignment_id: uuid.UUID,
    direction: str = Form(...),  # 'up' or 'down'
    db: Session = Depends(get_db),
):
    assignment = get_assignment(db, assignment_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    plan_id = assignment.study_plan_id
    reorder_assignment(db, assignment_id, direction)
    return RedirectResponse(
        url=f"/tutor/plans/{plan_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/plans/assignments/{assignment_id}/delete")
def post_delete_assignment(
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    assignment = get_assignment(db, assignment_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    plan_id = assignment.study_plan_id
    delete_assignment(db, assignment_id)
    return RedirectResponse(
        url=f"/tutor/plans/{plan_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
