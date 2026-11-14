# Implementation Plan: Academic Planner

## 1. Execution Methodology

To ensure stability and reliability under our incremental execution workflow, the project implementation is divided into **8 isolated, sequential stages**.

### Incremental Execution Rules
1. **Granular Operations**: Every implementation change is broken into logical, focused steps.
2. **Strict File Size Limits**: Individual file-writing tool calls must strictly remain under 100 lines. Larger additions are constructed iteratively.
3. **Automated Verification**: Each stage concludes with focused automated tests validating correctness before proceeding to the next stage.
4. **Zero Unapproved Scope Expansion**: No external dependencies or features outside this specification are added.

## 2. Stage Breakdown Overview

- **Stage 1**: Foundation, Project Scaffolding & Environment Setup
- **Stage 2**: Authentication, Session Management & User Administration
- **Stage 3**: Curriculum Domain (Subjects, Books, Chapters)
- **Stage 4**: Study Plans & Assignment Builder (Tutor Domain)
- **Stage 5**: Student Workspace & Assignment Completion Tracking
- **Stage 6**: External Examination Records
- **Stage 7**: Tutor & Student Analytics Dashboards
- **Stage 8**: Production Hardening, Nginx, Security Audit & Deployment Smoke Tests

## 3. Detailed Stage Specifications

### Stage 1: Foundation & Project Scaffolding
- **Goal**: Establish the base Python environment, Docker Compose configuration, FastAPI skeleton, database connection, and Alembic initialization.
- **Tasks**:
  1. Create `pyproject.toml` / `requirements.txt` with pinned dependencies (`fastapi`, `uvicorn`, `sqlalchemy`, `alembic`, `psycopg2-binary`, `pydantic-settings`, `jinja2`, `passlib[bcrypt]` or `argon2-cffi`).
  2. Configure `docker-compose.yml` (`web` service, `postgres:16-alpine` db service with `postgres_data` and `./backups:/var/lib/postgresql/backups` mounts, health checks).
  3. Create `app/core/config.py` with Pydantic settings.
  4. Create `app/core/database.py` with SQLAlchemy `engine`, `SessionLocal`, and `Base`.
  5. Initialize Alembic environment in `alembic/` and configure `env.py`.
- **Verification Gate**:
  - Test database connectivity via a basic health-check script/endpoint.
  - Run initial blank migration (`alembic upgrade head`).

### Stage 2: Authentication, Session Management & User Administration
- **Goal**: Implement secure session-based authentication with fixed 14-day expiration, anti-CSRF binding, and student account provisioning for the tutor.
- **Tasks**:
  1. Define `User` and `UserSession` models (`csrf_token`, fixed `expires_at = created_at + 14 days`, non-rolling) with migrations.
  2. Implement password hashing & verification utilities in `app/core/security.py`.
  3. Implement `AuthService` (login, fixed-expiry session token generation, session revocation).
  4. Implement CSRF protection middleware/dependency (`X-CSRF-Token` header check against session).
  5. Build login endpoint (`/auth/login`) and logout endpoint (`/auth/logout`) with HTTP-only cookie emission.
  6. Build authentication dependencies (`get_current_user`, `require_tutor`, `require_student`).
  7. Build tutor student management views: student list, student creation form, password reset.
- **Verification Gate**:
  - Unit tests for password hashing, session expiration, and anti-CSRF token verification.
  - Integration tests for login, invalid credentials, cookie validation, CSRF rejection, and session revocation.
  - Role-based authorization tests (student blocked from tutor endpoints).

### Stage 3: Curriculum Domain
- **Goal**: Enable the tutor to manage the full Subject -> Book -> Chapter hierarchy and test counts, establishing composite keys for assignment integrity.
- **Tasks**:
  1. Define `Subject`, `Book`, `Chapter` SQLAlchemy models with:
     - Check constraint: `total_tests >= 1`.
     - Unique constraints: `(id, subject_id)` on `books` and `(id, book_id)` on `chapters`.
  2. Generate and apply Alembic migration for curriculum tables.
  3. Implement `CurriculumService` with CRUD operations.
  4. Create tutor curriculum templates and HTMX-driven inline management views:
     - Subject creation & listing.
     - Book creation under selected subject.
     - Chapter creation with test counts.
- **Verification Gate**:
  - Test constraint validations (reject negative or zero test counts, reject duplicate subject names).
  - Test cascading/restricting foreign key behaviors.
  - Test HTMX partial rendering for adding/editing curriculum items.

### Stage 4: Study Plans & Assignment Builder
- **Goal**: Provide the tutor with tools to construct, schedule, and publish 14-day study plans with strict DB-level integrity guarantees.
- **Tasks**:
  1. Define `StudyPlan` and `Assignment` SQLAlchemy models with migrations:
     - StudyPlan constraint: `end_date = start_date + INTERVAL '13 days'`.
     - StudyPlan partial unique index: `uq_study_plans_one_published_per_student` (`student_id` WHERE `status = 'PUBLISHED'`).
     - StudyPlan unique constraint: `(id, student_id)`.
     - Assignment composite FK 1: `(study_plan_id, student_id) REFERENCES study_plans(id, student_id) ON DELETE CASCADE`.
     - Assignment composite FK 2: `(book_id, subject_id) REFERENCES books(id, subject_id) ON DELETE RESTRICT`.
     - Assignment composite FK 3: `(chapter_id, book_id) REFERENCES chapters(id, book_id) ON DELETE RESTRICT`.
  2. Implement `PlanService`:
     - Create 14-day plan shell for a designated student.
     - Add/remove/edit individual assignments (specifying subject, book, chapter, test start/end, scheduled date, deadline calculated as next local midnight UTC).
     - Transition plan status: `DRAFT` -> `PUBLISHED` -> `ARCHIVED`.
  3. Create tutor plan builder UI:
     - 14-day calendar / list view.
     - Dynamic dropdowns populated with curriculum chapters and test ranges.
     - "Publish Plan" confirmation modal.
- **Verification Gate**:
  - Schema test: attempt to insert assignment with mismatched student ID or mismatched book/subject and assert PostgreSQL foreign key violation.
  - Schema test: attempt to publish second active plan for same student and assert partial unique index violation.
  - Validation test: ensure assignment test range (`start_test <= end_test <= chapter.total_tests`) is enforced.
  - Validation test: ensure dates fall within the 14-day plan boundary.
  - Test draft visibility isolation (student cannot see draft plan).

### Stage 5: Student Workspace & Assignment Completion Tracking
- **Goal**: Allow students to view their 14-day study plan and mark assignments complete (one-way), while allowing tutors to reset accidental completions with audit logs.
- **Tasks**:
  1. Define `AssignmentCompletionAudit` model and migration.
  2. Implement `TrackingService` and dynamic status derivation logic:
     - `Pending`, `Completed on time`, `Completed late`, `Overdue and incomplete` based on exclusive cutoff `< deadline` (next local midnight UTC).
  3. Implement student plan view:
     - Group assignments by date with status badges.
     - One-click HTMX complete action (`POST /student/assignments/{id}/complete`).
     - Block students from unmarking completed assignments.
  4. Implement tutor reset completion action (`POST /tutor/assignments/{id}/reset-completion`) logging previous timestamp, actor, and reason into audit table.
- **Verification Gate**:
  - Test IDOR security: student A cannot mark student B's assignment complete.
  - Test one-way action: student cannot unmark completion.
  - Test tutor reset audit: resetting an assignment creates an `AssignmentCompletionAudit` record and clears `completed_at`.
  - Test re-completion captures a fresh server timestamp.
  - Test status derivation at boundary (1 second before midnight vs. exact midnight).

### Stage 6: External Examination Records
- **Goal**: Enable students to record external examination outcomes (with score, max_score, percentage, and rank) and allow tutor review.
- **Tasks**:
  1. Define `ExamResult` SQLAlchemy model (`score`, optional `max_score`, `percentage`, `rank_in_exam`) and migration.
  2. Implement `ExamService`:
     - Create, update, delete exam result strictly scoped to authenticated student (`current_user.id`).
     - List student's own exam results sorted by date.
     - Tutor view: inspect student's exam history from student detail page.
  3. Create student exam entry modal / page with validation (`score <= max_score`, `0 <= percentage <= 100`, `rank >= 1`).
- **Verification Gate**:
  - Test isolation: student cannot see or modify other students' exam results.
  - Test validation bounds for score, max_score, percentage, and ranking.
  - Verify absence of cross-student rankings or leaderboards.

### Stage 7: Analytics & Dashboards
- **Goal**: Build high-value, actionable dashboards for both student and tutor.
- **Tasks**:
  1. Implement `DashboardService` with efficient SQL aggregations:
     - Student metrics: active plan progress %, assignments due today, overdue count.
     - Tutor metrics: aggregate student progress, active plans count, list of students with overdue assignments ("falling behind" list).
  2. Implement Student Dashboard view (`/student/dashboard`).
  3. Implement Tutor Dashboard view (`/tutor/dashboard`) with quick filters for students needing attention.
- **Verification Gate**:
  - Test metric calculation accuracy across varying assignment completion states.
  - Test query efficiency (ensure no N+1 queries when rendering student list on tutor dashboard).

### Stage 8: Production Hardening, Nginx & Deployment Verification
- **Goal**: Finalize deployment configuration, security headers, backup scripts, and perform end-to-end smoke testing.
- **Tasks**:
  1. Configure `nginx/nginx.conf` (reverse proxy, rate limiting, gzip compression, static file cache headers, SSL setup).
  2. Write automated daily database backup script (`scripts/backup_db.sh`) targeting host mount `./backups`.
  3. Verify disaster recovery by restoring dump (`pg_restore`) into a test database.
  4. Verify CSRF protection, secure cookie flags, and CORS/CSP headers.
  5. Perform end-to-end smoke testing across desktop and mobile screen sizes.
- **Verification Gate**:
  - Full automated test suite passes (`pytest`).
  - Docker Compose up test confirms clean boot with automatic migrations and seeded tutor account.
  - Backup generation and restoration verification test succeeds cleanly.
