# Security & Business Logic Audit Progress

## Baseline vs Final Verification
- **Baseline (`.\.venv\Scripts\python.exe -m pytest -q`)**: `190 passed, 3 failed, 2 skipped (45.30s)`
  - Baseline failures: `test_auth_routes.py::test_logout` (missing CSRF token), `test_demo_generator.py::test_demo_generator_and_cleanup_lifecycle` (PostgreSQL offline on `localhost:15432`), `test_plan_service.py::test_create_and_publish_study_plan` (`IntegrityError` on `publish_study_plan`).
- **Final Verification (`.\.venv\Scripts\python.exe -m pytest -q` after all code/test edits)**: `1 failed, 206 passed, 2 skipped (49.32s)`
  - Remaining environment failure: `tests/test_demo_generator.py::test_demo_generator_and_cleanup_lifecycle` (`psycopg2.OperationalError` connecting to `localhost:15432` because PostgreSQL is not running in this local test environment; `tests/test_postgres_integration.py` accounts for the `2 skipped`).
  - Dependency check (`.\.venv\Scripts\python.exe -m pip check`): `No broken requirements found.`

## Completed Phases (Phases 1–8 — ALL DONE)
- **Phase 1 (Auth, sessions, authorization)**: Verified Argon2id, SHA-256 session tokens, 14-day expiry, CSRF middleware/dependencies, and RBAC. Replaced `!=` CSRF compare with `secrets.compare_digest` (`app/core/dependencies.py:88`). Added missing `csrf_token` + negative CSRF assertion in `tests/test_auth_routes.py`. Documented unresolved low/informational items (`new_password.strip()` on reset vs raw on auth, case-sensitive login lookup, in-memory rate limiter).
- **Phase 2 (Student/tutor isolation & IDOR)**:
  - Fixed High IDOR/state mutation in `app/services/practice_exam_service.py` (`get_student_booklet_state` `student_id` check before timer lock commit) and `app/routers/student_practice_exams.py` (added ownership checks on form save/submit, download, runner, and results page prior to status inspection).
  - Enforced `exam.is_active` in `start_practice_attempt` and `download_student_practice_booklet`.
- **Phase 3 (Study plans, deadlines, completion)**:
  - Fixed High `IntegrityError` in `publish_study_plan` (`db.flush()` before `PlanStatus.PUBLISHED`).
  - Fixed High draft plan leakage (`exclude_drafts=True` in `get_study_plan`, `list_student_plans`, and `app/routers/student.py`).
  - Fixed Medium hierarchy/state integrity checks in `app/services/plan_service.py` (`create_study_plan` student role guard, `create_assignment` course/book chapter ownership & video count bounds, `delete_assignment`/`reorder_assignment` `ARCHIVED` guard, `reset_assignment_completion` pending check, `undo_assignment_completion` `.with_for_update()`).
  - Documented spec drift between `docs/PRODUCT_SPEC.md` / `docs/AUTHORIZATION.md` ("students cannot undo") and implemented `undo_assignment_completion` (intentionally preserved with locking & audit log).
- **Phase 4 (Exams, results, scoring, data integrity)**:
  - Fixed High eligibility bypass, archived/inactive enforcement, forged `reporting_group_id`, and concurrent duplicate `IntegrityError` in `app/services/exam_service.py` (`submit_student_exam_result`, `update_student_exam_result`, `get_student_available_exams`, `tutor_correct_exam_result`).
  - Fixed High `NaN`/`Inf` float bypass (`_validate_percentage`), `update_exam_session` `NameError`, `get_exam_series_analytics` >100% submission rate bug, and `configure_practice_exam_questions` deleting questions prior to validating inputs (`practice_exam_service.py`).
  - Fixed deferred-validation deletion ordering in `update_exam_session`, `tutor_correct_exam_result`, and `update_student_exam_result`.
- **Phase 5 (API validation, CSRF, XSS, uploads, redirects)**:
  - Fixed orphaned file writes and out-of-order validation in `app/routers/student_exams.py`, `app/routers/tutor_historical_exams.py`, and `app/routers/tutor_practice_exams.py` (including cleanup of replaced report card on edit).
  - Fixed broken chat pagination `+00:00` query encoding (`quote(..., safe="")`) in `app/routers/student_chat.py` and `app/routers/tutor_messages.py`.
  - Added `http(s)://` scheme validation to `_validate_meeting_url` in `app/services/meeting_service.py`.
  - Fixed uncaught `ValueError` HTTP 500s on malformed dates/numbers across `tutor_plans.py`, `tutor_exams.py`, `tutor_historical_exams.py`, `tutor_practice_exams.py`, `tutor_scheduler.py`, `student_exams.py`, `student_practice_exams.py`, and URL-encoded `?err=` query parameters (`tutor.py`, `tutor_exams.py`, `tutor_practice_exams.py`, `tutor_subjects.py`).
- **Phase 6 (Transactions, concurrency, race conditions)**:
  - Fixed split-commit race in `submit_booklet_answers` (`practice_exam_service.py`) by calculating results inside the same transaction as `COMPLETED`.
  - Converted per-iteration `db.commit()` in `generate_series_sessions`, `update_future_recurrence`, `extend_exam_recurrence`, `bulk_add_manual_sessions` to single transaction commits (`commit=False`).
  - Added missing FK usage checks (`PlanAssignment`, `ExamSubjectConfiguration`, `StudentExamSubjectResult`, `PracticeExamQuestion`) to `delete_subject` in `app/services/academic_service.py`.
  - Documented `get_due_reminders` lacking `.with_for_update(skip_locked=True)` (`meeting_service.py:423-462`).
- **Phase 7 (Deployment & dependencies)**:
  - Changed `Settings.DEBUG` default from `True` to `False` (`app/core/config.py:10`).
  - Disabled `/docs`, `/redoc`, `/openapi.json`, and `"docs"` root metadata when `ENVIRONMENT == "production"` (`app/main.py:30-39, 172`).
  - Documented minor infra notes (`Dockerfile:34` `--forwarded-allow-ips=*`, `docker-compose.yml:45` port `18000` vs `nginx/valhalla.conf:6` port `8000`).
- **Phase 8 (Regression testing & final verification)**:
  - Added 16 new regression tests in `tests/test_security_audit_regressions.py` + updated `tests/test_auth_routes.py` (`test_logout_requires_csrf`, `test_logout`).

## Remaining / Unresolved Work (Environment & Low-Risk Decisions)
- PostgreSQL-backed lifecycle tests (`tests/test_demo_generator.py` and `tests/test_postgres_integration.py`) require a running PostgreSQL instance on `localhost:15432` to verify PostgreSQL-specific constraints and row locking end-to-end.
- Intentional/low-risk items documented for maintainer decision: spec drift on student assignment undo, `get_due_reminders` row locking, `new_password.strip()`, in-memory rate limiting / `Dockerfile` proxy flags, and `docker-compose.yml` vs `nginx/valhalla.conf` port mapping.
