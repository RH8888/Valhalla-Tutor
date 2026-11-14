# System Architecture: Academic Planner

## 1. System Overview & Principles
The Valhalla Academic Planner is designed as a monolithic server-rendered web application tailored for a single VPS deployment managing ~100 users.

### Architectural Principles
- **Monolithic Simplicity**: A single Python/FastAPI process renders UI and serves endpoints. No microservices, message queues, or distributed coordination.
- **Server-Driven UI**: Fast server-side rendering with Jinja2 templates augmented by HTMX for reactive, single-page-app-like interactions without JavaScript build tooling.
- **Zero Heavy Background Infrastructure**: Because the user base is ~100 students, background worker queues (Celery/Redis) are omitted. Computations and aggregations are optimized directly within PostgreSQL queries.
- **Secure by Default**: Cookie-based HTTP-only session authentication with strict query-level student data isolation.

## 2. High-Level Architecture

```
[ Web Browser (Student / Tutor) ]
             |
             | HTTPS (Port 443)
             v
   [ Nginx Reverse Proxy ]
   - SSL / TLS termination
   - Static asset caching (/static/)
   - Rate limiting & request buffering
             |
             | HTTP (Uvicorn UNIX socket or local port 8000)
             v
   [ FastAPI Application Container ]
   - Session Auth & Role-Based Middleware
   - Jinja2 Template Engine + HTMX Partials
   - Service / Domain Logic Layer
   - SQLAlchemy 2.0 ORM (Async / Sync Session)
             |
             | PostgreSQL Wire Protocol (Port 5432)
             v
   [ PostgreSQL Container ]
   - Relational schema with foreign keys
   - Timezone-aware UTC timestamps
   - Automated daily logical backups (pg_dump volume)
```

## 3. Application Structure

The application adopts a modular, domain-oriented structure within `app/`:

```
app/
├── core/
│   ├── config.py           # Pydantic Settings (ENV variables, secrets)
│   ├── security.py         # Password hashing (Argon2 / bcrypt), session token generation
│   ├── database.py         # SQLAlchemy Engine, SessionLocal, base model
│   └── timezone.py         # Timezone conversion helpers (UTC <-> Local)
├── models/
│   ├── base.py             # DeclarativeBase with common timestamp mixins
│   ├── user.py             # User model (TUTOR, STUDENT)
│   ├── session.py          # UserSession (token hash, csrf_token, fixed 14-day expiry)
│   ├── curriculum.py       # Subject, Book, Chapter models (with composite FK keys)
│   ├── study_plan.py       # StudyPlan model (14-day constraint, partial unique index)
│   ├── assignment.py       # Assignment model (composite FK to plan & student, book, chapter)
│   ├── audit.py            # AssignmentCompletionAudit model (for tutor resets)
│   └── exam_result.py      # ExamResult model (score, max_score, percentage)
├── schemas/
│   ├── curriculum.py       # Validation schemas for curriculum inputs
│   ├── study_plan.py       # Validation schemas for plans & assignments
│   └── exam_result.py      # Validation schemas for exams
├── services/
│   ├── auth_service.py     # Login, logout, session verification
│   ├── curriculum_service.py # CRUD operations for curriculum
│   ├── plan_service.py     # Plan lifecycle, assignment generation
│   ├── tracking_service.py # Assignment completion & status calculation
│   ├── exam_service.py     # Exam recording logic
│   └── dashboard_service.py# Aggregations for tutor & student dashboards
├── routers/
│   ├── auth.py             # Login, logout routes
│   ├── tutor.py            # Tutor dashboard, student management, curriculum, plan editor
│   ├── student.py          # Student dashboard, plan view, assignment toggle, exam entry
│   └── partials.py         # Dedicated HTMX endpoints returning HTML fragments
├── templates/
│   ├── base.html           # Base layout (Tailwind CSS, HTMX CDN script)
│   ├── auth/               # Login templates
│   ├── tutor/              # Tutor pages & plan builder
│   ├── student/            # Student dashboard & assignment views
│   └── components/         # Reusable Jinja2/HTMX partials (cards, badges, modals)
└── static/
    ├── css/                # Pre-built Tailwind CSS stylesheet
    └── js/                 # HTMX extension helpers (CSRF handling, notifications)
```

## 4. Request Flow & HTMX Server-Rendered Pattern

Instead of an asynchronous Single Page Application (SPA) requiring a separate frontend build and REST/GraphQL API layer, the application uses **Server-Side Rendering (SSR) with Hypermedia Controls (HTMX)**:

1. **Standard Page Requests**:
   - Browser sends GET request to `/student/dashboard`.
   - Router invokes `get_current_active_user` dependency.
   - Router queries `dashboard_service.py` to retrieve active plan, today's assignments, and metrics.
   - Full HTML page rendered using Jinja2 (`templates/student/dashboard.html`) extending `base.html`.

2. **Reactive Interactions (e.g. Assignment Completion & Tutor Reset)**:
   - **Student Completion**:
     - User clicks "Mark Complete" button.
     - HTMX issues a `POST /student/assignments/{assignment_id}/complete` carrying the `X-CSRF-Token` header.
     - Backend verifies that `assignment_id` belongs to the authenticated student and is not already completed.
     - Server records `completed_at = NOW()` in an atomic transaction.
     - Backend returns the updated row partial displaying completed status (student cannot unmark).
   - **Tutor Administrative Reset**:
     - If marked accidentally, the tutor clicks "Reset Completion" on the student's detail view.
     - HTMX issues `POST /tutor/assignments/{assignment_id}/reset-completion` with an optional reason.
     - Backend verifies tutor authorization, creates an `AssignmentCompletionAudit` log, and clears `completed_at = NULL`.
     - Subsequent re-completion by student will capture a brand-new server timestamp.

3. **Error Handling & Feedback**:
   - HTMX requests receiving validation errors, CSRF mismatches, or unauthorized status return toast notification fragments or inline field error badges with appropriate HTTP response codes (e.g., 403 Forbidden, 422 Unprocessable Entity).

## 5. Authentication, Fixed Session & CSRF Strategy

### 5.1 Fixed Session Lifetime (Non-Rolling)
- Standard HTTP-only, `SameSite=Lax`, `Secure=True` cookie (`valhalla_session`) containing a 256-bit cryptographically secure token.
- Stored in database entity `UserSession`:
  - `id` (UUID PK)
  - `user_id` (FK to User)
  - `token_hash` (SHA-256 hash of the session token)
  - `csrf_token` (Cryptographically secure anti-CSRF token string)
  - `created_at` (TIMESTAMPTZ default `NOW()`)
  - `expires_at` (TIMESTAMPTZ): **Strict fixed expiration** set at login to exactly `created_at + 14 days`.
  - `is_revoked` (Boolean flag)
- **Security Rule**: Session expiration is strictly fixed (non-rolling). Active sessions terminate immediately once `NOW() >= expires_at`, preventing perpetual session immortality. Re-authentication is required after 14 days.

### 5.2 CSRF Protection Architecture
- Each active `UserSession` generates a persistent `csrf_token`.
- Rendered into every HTML page via `<meta name="csrf-token" content="{{ current_user_session.csrf_token }}">`.
- Included in all HTMX requests via global HTMX configuration:
  ```javascript
  document.body.addEventListener('htmx:configRequest', (event) => {
    event.detail.headers['X-CSRF-Token'] = document.querySelector('meta[name="csrf-token"]').content;
  });
  ```
- FastAPI middleware/dependency verifies that `request.headers.get("X-CSRF-Token") == session.csrf_token` on all unsafe methods (`POST`, `PUT`, `DELETE`). If missing or mismatched, an immediate `403 Forbidden` response is returned.

### 5.3 Why Server-Side Sessions over Stateless JWTs?
1. **Instant Revocation**: If a student forgets credentials or the tutor deactivates an account, the session can be instantly invalidated in the database.
2. **Simplified Invalidation**: Logout cleanly terminates the session without complex JWT blacklisting or external Redis caches.
3. **Low Load**: For ~100 users, database session lookups are trivial (<1ms over a local indexed connection).

## 6. Deployment & Operational Architecture

### Docker Compose Architecture
The entire application runs on a single VPS with Docker Compose comprising two services:
1. `web`: Python 3.12 + FastAPI running behind Uvicorn with 2-4 worker processes.
2. `db`: Official `postgres:16-alpine` container with:
   - `postgres_data:/var/lib/postgresql/data` (persistent database volume)
   - `./backups:/var/lib/postgresql/backups` (host-mounted backup target)

### Nginx Reverse Proxy (Host or Container)
- Terminates SSL using Let's Encrypt / Certbot.
- Forwards `/` traffic to FastAPI container.
- Serves `/static/` files directly with gzip compression and cache headers.
- Implements connection rate limiting (`limit_req_zone`) to protect login routes against brute-force attacks.

### Backup & Disaster Recovery Runbook
- **Automated Backup Command**:
  ```bash
  mkdir -p ./backups
  docker compose exec -T db pg_dump -U postgres -d valhalla_db -F c -b -v -f /var/lib/postgresql/backups/valhalla_$(date +%Y%m%d_%H%M%S).dump
  ```
- **Retention**: Keep daily backups for 30 days and weekly backups for 6 months using logrotate or cleanup scripts.
- **Restoration Command**:
  ```bash
  docker compose exec -T db pg_restore -U postgres -d valhalla_db -c -v /var/lib/postgresql/backups/target_file.dump
  ```
