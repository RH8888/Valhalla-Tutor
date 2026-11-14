# Authorization Design: Academic Planner

## 1. Core Principles & Philosophy

### 1.1 The Golden Rule: Never Trust Client-Supplied Identifiers
When an authenticated student performs an action or requests a resource, their identity is derived **strictly from their verified server-side session**. The application must **never** accept or honor a `student_id` passed in request query parameters, URL path variables, or form bodies from a student.
- For a student, `current_user.id` is the **only** permitted filter key.
- If a student issues a request to modify an assignment, the query explicitly matches `WHERE id = :assignment_id AND student_id = :current_user_id`. Attempting to access an assignment belonging to another student will result in an immediate `404 Not Found` (to avoid information disclosure) or `403 Forbidden`.

### 1.2 Strict Role-Based Separation
The system defines two mutually exclusive roles:
1. `TUTOR`: Administrative access to manage curriculum, create/publish study plans, inspect all students' progress, and administer student accounts.
2. `STUDENT`: Scoped access strictly limited to their own active and archived study plans, their own assignments, and their own examination records.

## 2. Permissions Matrix

| Resource / Action | Tutor | Student | Enforcement Rule |
| :--- | :---: | :---: | :--- |
| **Manage Students (CRUD, Reset Password)** | Allowed | Denied | Tutor-only route |
| **Manage Curriculum (Subjects, Books, Chapters)**| Allowed | Denied | Tutor-only route |
| **Create / Edit / Publish Study Plan** | Allowed | Denied | Tutor-only route |
| **View Study Plan** | Allowed (All) | Allowed (Own) | Student query filtered by `current_user.id` |
| **Create / Edit Assignment** | Allowed | Denied | Tutor-only route |
| **Mark Assignment Complete** | Denied | Allowed (Own) | One-way action; Student cannot undo |
| **Reset Assignment Completion** | Allowed | Denied | Tutor-only route; produces immutable audit log |
| **View Tutor Dashboard & Reports** | Allowed | Denied | Tutor-only route |
| **View Student Dashboard** | Denied | Allowed (Own) | Student sees only their assigned metrics & tasks |
| **Create / Edit / Delete Exam Result** | Allowed (View/Edit) | Allowed (Own) | Student manages own; Tutor can view/review |

## 3. Dependency Injection Pattern in FastAPI

Authorization is enforced declaratively using FastAPI dependencies before route handlers execute:

```python
# app/core/dependencies.py
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from app.models.user import User, UserRole
from app.services.auth_service import get_user_from_session

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    session_token = request.cookies.get("valhalla_session")
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user = get_user_from_session(db, session_token)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive or invalid session")
    return user

def require_tutor(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.TUTOR:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tutor privileges required")
    return user

def require_student(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.STUDENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Student privileges required")
    return user
```

## 4. Query-Level Data Isolation

To prevent Insecure Direct Object References (IDOR), services must enforce tenant filters at the query level:

### Student Completion & Tutor Reset Scoping
```python
# app/services/tracking_service.py
def mark_assignment_complete(db: Session, assignment_id: UUID, student_id: UUID) -> Assignment:
    # Query strictly filters by student_id to prevent modifying other students' data
    assignment = db.query(Assignment).filter(
        Assignment.id == assignment_id,
        Assignment.student_id == student_id
    ).first()
    
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
        
    if assignment.completed_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assignment already completed")
        
    assignment.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(assignment)
    return assignment

def reset_assignment_completion(
    db: Session, assignment_id: UUID, tutor_id: UUID, reason: str | None = None
) -> Assignment:
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
    if assignment.completed_at is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assignment is not completed")

    # Record immutable audit entry
    audit = AssignmentCompletionAudit(
        assignment_id=assignment.id,
        reset_by_user_id=tutor_id,
        previous_completed_at=assignment.completed_at,
        reset_at=datetime.now(timezone.utc),
        reason=reason
    )
    db.add(audit)
    assignment.completed_at = None
    db.commit()
    db.refresh(assignment)
    return assignment
```

### Study Plan Scoping
- Students may only query `StudyPlan` where `student_id == current_user.id` and `status == 'PUBLISHED'` (or `'ARCHIVED'`).
- Any attempt to view a `DRAFT` plan returns `404 Not Found`.
- Tutor endpoints receive the target student's ID from route parameters (e.g., `/tutor/students/{student_id}/plans`), which are valid because the caller has been authenticated as a `TUTOR`.

## 5. Security & Threat Mitigations

### 5.1 CSRF (Cross-Site Request Forgery) Protection
Because authentication relies on browser cookies, all state-modifying requests (`POST`, `PUT`, `DELETE`) are strictly protected against CSRF:
1. Upon session creation, a cryptographically secure random token (`csrf_token`) is stored in `user_sessions`.
2. The active token is rendered into base templates: `<meta name="csrf-token" content="{{ session.csrf_token }}">`.
3. HTMX includes this token on all AJAX requests via `hx-headers`:
   ```javascript
   document.body.addEventListener('htmx:configRequest', (evt) => {
       evt.detail.headers['X-CSRF-Token'] = document.querySelector('meta[name="csrf-token"]').content;
   });
   ```
4. A FastAPI dependency `verify_csrf_token` checks `request.headers.get("X-CSRF-Token") == session.csrf_token` on all unsafe methods. Requests with missing or invalid tokens are rejected with `403 Forbidden`.

### 5.2 Cookie Hardening & Fixed Session Expiration
- Session cookie (`valhalla_session`) uses flags: `HttpOnly=True`, `Secure=True` (in production), `SameSite='Lax'`, `Path='/'`.
- **Fixed 14-Day Expiration**: The session `expires_at` is fixed at creation time (`NOW() + 14 days`). The application never extends active sessions on activity (non-rolling). Once expired, the session is rejected.

### 5.3 Database-Level Multi-Tenant Isolation
In addition to application query filtering, PostgreSQL schema constraints prevent cross-tenant assignment links:
- `study_plans` enforces `UNIQUE (id, student_id)`.
- `assignments` enforces `FOREIGN KEY (study_plan_id, student_id) REFERENCES study_plans(id, student_id) ON DELETE CASCADE`.
- Even if an application bug attempts to insert an assignment with `student_id = X` and `study_plan_id = Y` (where Y belongs to student Z), PostgreSQL rejects the write at the storage engine level.

### 5.4 Brute Force & Rate Limiting
- Login endpoints (`/auth/login`) are rate-limited via Nginx `limit_req` (5 requests per minute per IP) to mitigate brute-force password guessing.
- Passwords are encrypted using Argon2id or bcrypt with appropriate work factors.
