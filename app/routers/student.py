import uuid
from datetime import date, timedelta
from typing import Dict, List, Tuple
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_session, get_current_user, require_student, verify_csrf_token
from app.core.templates import templates
from app.models.plan import PlanAssignment
from app.models.session import UserSession
from app.models.user import User
from app.services.academic_service import get_student_effective_subjects
from app.services.plan_service import (
    AssignmentNotFoundError,
    calculate_plan_totals,
    complete_assignment,
    format_duration_minutes,
    get_active_student_plan,
    get_assignment,
    get_student_completion_history,
    get_student_dashboard_data,
    get_study_plan,
    list_student_plans,
    PlanValidationError,
)
from app.services.resource_service import list_books, list_courses

router = APIRouter(
    prefix="/student",
    tags=["student"],
    dependencies=[Depends(require_student), Depends(verify_csrf_token)],
)


@router.get("/profile")
def get_student_profile(current_user: User = Depends(get_current_user)):
    """Simple authenticated student-only endpoint for Stage 2 authorization validation."""
    return {
        "id": str(current_user.id),
        "username": current_user.username,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "timezone": current_user.timezone,
    }


@router.get("/dashboard", response_class=HTMLResponse)
def get_student_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    dashboard_data = get_student_dashboard_data(db, current_user)
    return templates.TemplateResponse(
        request=request,
        name="student/dashboard.html",
        context={
            "data": dashboard_data,
            "student": current_user,
            "current_user": current_user,
            "current_session": current_session,
        },
    )



@router.get("/curriculum", response_class=HTMLResponse)
def get_student_curriculum(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    effective_subjects = get_student_effective_subjects(current_user)
    courses_by_subject = {}
    books_by_subject = {}
    for sub in effective_subjects:
        courses_by_subject[sub.id] = list_courses(db, subject_id=sub.id)
        books_by_subject[sub.id] = list_books(db, subject_id=sub.id)

    return templates.TemplateResponse(
        request=request,
        name="student/curriculum.html",
        context={
            "student": current_user,
            "track": current_user.academic_track,
            "is_customized": current_user.is_subjects_customized,
            "effective_subjects": effective_subjects,
            "courses_by_subject": courses_by_subject,
            "books_by_subject": books_by_subject,
            "current_user": current_user,
            "current_session": current_session,
        },
    )




@router.get("/plan", response_class=HTMLResponse)
def get_student_active_plan(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    plan = get_active_student_plan(db, current_user.id)
    if not plan:
        return templates.TemplateResponse(
            request=request,
            name="student/plan_empty.html",
            context={
                "student": current_user,
                "current_user": current_user,
                "current_session": current_session,
            },
        )

    effective_subjects = get_student_effective_subjects(current_user)
    assignments = plan.assignments
    days = [plan.start_date + timedelta(days=i) for i in range(14)]

    daily_totals, subject_totals, plan_total = calculate_plan_totals(assignments, days, effective_subjects)
    daily_totals_formatted = {d: format_duration_minutes(m) for d, m in daily_totals.items()}
    subject_totals_formatted = {sub_id: format_duration_minutes(m) for sub_id, m in subject_totals.items()}
    plan_total_formatted = format_duration_minutes(plan_total)

    assignments_by_cell: Dict[Tuple[date, uuid.UUID], List[PlanAssignment]] = {}
    completed_count = 0
    for a in assignments:
        key = (a.scheduled_date, a.subject_id)
        if key not in assignments_by_cell:
            assignments_by_cell[key] = []
        assignments_by_cell[key].append(a)
        if a.is_completed:
            completed_count += 1

    return templates.TemplateResponse(
        request=request,
        name="student/plan.html",
        context={
            "plan": plan,
            "student": current_user,
            "effective_subjects": effective_subjects,
            "days": days,
            "assignments_by_cell": assignments_by_cell,
            "daily_totals": daily_totals,
            "daily_totals_formatted": daily_totals_formatted,
            "subject_totals": subject_totals,
            "subject_totals_formatted": subject_totals_formatted,
            "plan_total": plan_total,
            "plan_total_formatted": plan_total_formatted,
            "completed_count": completed_count,
            "total_assignments_count": len(assignments),
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.get("/plans/history", response_class=HTMLResponse)
def get_student_plans_history(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    all_plans = list_student_plans(db, current_user.id)
    plans_data = []
    for p in all_plans:
        total_tasks = len(p.assignments)
        completed_tasks = sum(1 for a in p.assignments if a.is_completed)
        pct = round((completed_tasks / total_tasks) * 100) if total_tasks > 0 else 0
        total_minutes = sum(a.recommended_duration_minutes or 0 for a in p.assignments)
        plans_data.append({
            "plan": p,
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "completion_percentage": pct,
            "total_minutes": total_minutes,
            "total_formatted": format_duration_minutes(total_minutes),
        })

    return templates.TemplateResponse(
        request=request,
        name="student/plans_history.html",
        context={
            "student": current_user,
            "plans_data": plans_data,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.get("/plans/{plan_id}", response_class=HTMLResponse)
def get_student_plan_detail(
    plan_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    plan = get_study_plan(db, plan_id)
    if not plan or plan.student_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")

    effective_subjects = get_student_effective_subjects(current_user)
    assignments = plan.assignments
    days = [plan.start_date + timedelta(days=i) for i in range(14)]

    daily_totals, subject_totals, plan_total = calculate_plan_totals(assignments, days, effective_subjects)
    daily_totals_formatted = {d: format_duration_minutes(m) for d, m in daily_totals.items()}
    subject_totals_formatted = {sub_id: format_duration_minutes(m) for sub_id, m in subject_totals.items()}
    plan_total_formatted = format_duration_minutes(plan_total)

    assignments_by_cell: Dict[Tuple[date, uuid.UUID], List[PlanAssignment]] = {}
    completed_count = 0
    for a in assignments:
        key = (a.scheduled_date, a.subject_id)
        if key not in assignments_by_cell:
            assignments_by_cell[key] = []
        assignments_by_cell[key].append(a)
        if a.is_completed:
            completed_count += 1

    from app.models.plan import PlanStatus
    is_archived = (plan.status != PlanStatus.PUBLISHED)

    return templates.TemplateResponse(
        request=request,
        name="student/plan.html",
        context={
            "plan": plan,
            "student": current_user,
            "effective_subjects": effective_subjects,
            "days": days,
            "assignments_by_cell": assignments_by_cell,
            "daily_totals": daily_totals,
            "daily_totals_formatted": daily_totals_formatted,
            "subject_totals": subject_totals,
            "subject_totals_formatted": subject_totals_formatted,
            "plan_total": plan_total,
            "plan_total_formatted": plan_total_formatted,
            "completed_count": completed_count,
            "total_assignments_count": len(assignments),
            "is_archived": is_archived,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.get("/history", response_class=HTMLResponse)
def get_student_history(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    completed_tasks = get_student_completion_history(db, current_user.id)
    return templates.TemplateResponse(
        request=request,
        name="student/history.html",
        context={
            "student": current_user,
            "completed_tasks": completed_tasks,
            "current_user": current_user,
            "current_session": current_session,
        },
    )


@router.post("/assignments/{assignment_id}/complete", response_class=HTMLResponse)
def post_complete_assignment(
    assignment_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    try:
        assignment = complete_assignment(db, assignment_id, current_user.id)
    except AssignmentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
    except PlanValidationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    # If request is HTMX, return updated task card snippet
    if request.headers.get("HX-Request"):
        view_type = request.query_params.get("view")
        template_name = "student/partials/dashboard_task_item.html" if view_type == "dashboard" else "student/partials/task_card.html"
        return templates.TemplateResponse(
            request=request,
            name=template_name,
            context={
                "assignment": assignment,
                "current_user": current_user,
                "current_session": current_session,
            },
        )

    return HTMLResponse('<div class="text-xs text-emerald-600 font-semibold">Completed!</div>')

