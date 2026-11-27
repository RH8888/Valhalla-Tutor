# Valhalla Tutor — Production Audit Progress Log

**Audit Scope:** Real-world production readiness & scalability for **2–3 tutors, up to 100 students, single Ubuntu VPS (2 CPU cores, 4 GB RAM), Docker Compose + host Nginx + PostgreSQL 16**.  
**Mode:** Assessment only (zero application code, dependency, database, or infrastructure modifications).

---

## Completed Areas

| Area | Scope Inspected | Status |
|---|---|---|
| Repo & Config | `Dockerfile`, `docker-compose.yml`, `docker-compose.dev.yml`, `nginx/valhalla.conf`, `scripts/entrypoint.sh`, `docs/DEPLOYMENT.md`, `.env`, `.env.example`, `.gitignore`, `.dockerignore`, `pyproject.toml`, `requirements.txt`, `uploads/`, `backups/`, `app/static/` | Completed |
| Core & App Bootstrap | `app/main.py`, `app/cli.py`, `app/routers/health.py`, `app/schemas/health.py`, `app/core/*` (`config.py`, `database.py`, `dependencies.py`, `security.py`, `rate_limit.py`, `storage.py`, `i18n.py`, `templates.py`, `timezone.py`) | Completed |
| Database & Migrations | All `app/models/*.py`, `alembic.ini`, `alembic/env.py`, all 19 `alembic/versions/*.py`; ran `alembic upgrade head --sql`, SQLite `alembic upgrade head`, and `alembic check` | Completed |
| Business Services | `auth_service.py`, `user_service.py`, `tutor_provision.py`, `academic_service.py`, `resource_service.py`, `message_service.py`, `plan_service.py`, `meeting_service.py`, `scheduler_service.py`, `practice_exam_service.py`, `exam_service.py` | Completed |
| HTTP Routers & Templates | All 18 routers in `app/routers/*.py`, `app/static/js/i18n.js`, critical templates (`base.html`, `mobile_nav_drawer.html`, `auth/login.html`, `student/dashboard.html`, `student/plan.html`, `student/chat.html`, `runner.html`, `task_card.html`, `dashboard_task_item.html`, `student/exams/analytics.html`, `tutor/exams/student_analytics.html`, `tutor/exams/session_detail.html`, `tutor/students/*`, `tutor/plans/planner.html`, `tutor/messages/inbox.html`, `tutor/calendar/*`, `message_bubble.html`) | Completed |
| Automated Verification | `pytest --collect-only -q` (`228` collected tests across `38` files); ran `19` non-`TestClient`/non-PG unit & workflow test files (`105 passed`); ran `test_demo_generator.py` (`1 failed` — no PG on `localhost:15432`); inspected `test_postgres_integration.py` (`5` tests skipped without PG) | Completed (sandbox limits noted) |

---

## Verification & Unverified Boundaries

- **Verified passing locally:** `105` service/workflow/security unit tests across `19` SQLite/pure-Python test files (`.venv\Scripts\python.exe -m pytest ...`, `11.45s`, `26` warnings).
- **Verified Alembic chain (SQLite):** `alembic upgrade head` succeeded to `2c3d4e5f6a7b (head)`; `alembic check` failed (`exit 1`) reporting 3 missing indexes + redundant unique constraints on `subjects`/`academic_tracks`; `alembic upgrade head --sql` failed at `0a1b2c3d4e5f:27` (`AttributeError` on `NoneType.fetchall`).
- **Failed / Unverified in sandbox:**
  - `tests/test_demo_generator.py` (1 test) failed connecting to PostgreSQL on `localhost:15432` (`Permission denied`).
  - `tests/test_postgres_integration.py` (5 tests) requires live PostgreSQL (not executed here).
  - `17` test files (`117` tests) using FastAPI/Starlette `TestClient` stalled inside the Windows sandbox on `TestClient(app)` socket/portal initialization and remain **unverified at runtime**.
  - No live Linux Docker Compose / PostgreSQL 16 / Nginx stack was started, no load testing was performed, and no `pip-audit` network CVE check was run.

---

## Finding Index Summary (31 Actionable + 5 Optional)

- **Category 1 — Critical blockers (5):** `CRIT-01` (Nginx/Compose port `8000` vs `18000`), `CRIT-02` (Practice exam timed auto-submit wipes saved answers), `CRIT-03` (2–3 tutor support broken in CLI, chat, scheduler, plans), `CRIT-04` (No automated/off-VPS backups or tested restore), `CRIT-05` (`fa` locale HTML placeholder XSS).
- **Category 2 — High-priority fixes (9):** `HIGH-01` (Weak default DB password / unused `SECRET_KEY` / no prod startup checks), `HIGH-02` (`2G+2G=4G` RAM caps + untuned Postgres/pool), `HIGH-03` (4 unpinned external CDNs + Play CDN forcing `unsafe-inline`/`unsafe-eval`), `HIGH-04` (No upload magic bytes + sync I/O blocking `async def` routes), `HIGH-05` (Per-worker IP rate limit, timing username enum, case-sensitive login, Nginx limiting `GET /auth/login`), `HIGH-06` (`get_due_reminders` race + duplicate navbar pollers + missing `#modal-container`), `HIGH-07` (Uncaught 500s + unquoted `str(exc)` Location header crashes), `HIGH-08` (Full-table Python queries in exam/practice + `2N+1` inbox + blocking `async def`), `HIGH-09` (Naive `submission_deadline` timezone drift).
- **Category 3 — Easy fixes (9):** `EASY-01`..`EASY-09` (manifest sync, 3 missing indexes, offline Alembic & `Query.get`, demo PDFs in image, login CSRF/session GC/`secure` cookie dev toggle, `--forwarded-allow-ips` & Nginx hardening, input length/duplicate race checks, CI full pytest + `pip-audit`, duplicate unread badge polling cleanup).
- **Category 4 — Moderate improvements (5):** `MOD-01`..`MOD-05` (self-service password change/policy, HTML error pages & 401 login redirect, scheduler proposal guards & display_order lock, structured logging & upload GC, retire HTML regex i18n).
- **Category 5 — Hard / expensive problems (3):** `HARD-01`..`HARD-03` (WebSockets/SSE across workers, full async ORM rewrite, multi-tenant business isolation — none needed pre-launch).
- **Category 6 — Optional / unnecessary (5):** `OPT-01`..`OPT-05` (Redis, Celery, Kubernetes, S3 runtime proxy, DB read replicas/PgBouncer).

---

## Final Verdict

- **Verdict:** **Not production-ready — moderate work required.**
- **Overall Score:** **4.5 / 10**
- **Report:** Written to `PRODUCTION_READINESS_REPORT.md`.
