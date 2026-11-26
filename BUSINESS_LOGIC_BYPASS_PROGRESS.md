# Business Logic Bypass Remediation Progress

## Environment & Baseline Notes
- **PostgreSQL / Docker status**: Docker Desktop engine is offline (`//./pipe/dockerDesktopLinuxEngine` not available) and ports `15432` / `5432` are closed locally. SQLite in-memory tests and FastAPI `TestClient` tests execute outside sandbox (`BypassSandbox: true` due to Windows `socketpair()` limit).
- **Scanner ignored items**: No separate scanner output / SARIF file is present in the workspace, so the 11 ignored items could not be inspected.

## Phase 1 — Practice Exams (DONE)
- **Finding #1 (Confirmed — Genuine Logic & Concurrency Bypass)**:
  - *Root Cause*: `add_practice_exam_booklet` (`app/services/practice_exam_service.py`) did not check whether `StudentPracticeAttempt` records already existed and did not lock `PracticeExam` against concurrent `start_practice_attempt`. Once an attempt started, adding a booklet altered `submit_booklet_answers` progression dynamically while `configure_practice_exam_questions` blocked adding question definitions for existing attempts.
  - *Fix*: Acquire exclusive `.with_for_update()` lock on `PracticeExam.id` in `add_practice_exam_booklet` and `configure_practice_exam_questions`, acquire share `.with_for_update(read=True)` lock on `PracticeExam.id` in `start_practice_attempt` (keeping lock order `User -> PracticeExam`), and raise `PracticeExamValidationError` in `add_practice_exam_booklet` when any `StudentPracticeAttempt` exists.
  - *Files Changed*: `app/services/practice_exam_service.py`, `tests/test_business_logic_bypass.py`.
  - *Tests*: `.\.venv\Scripts\python.exe -m pytest tests/test_practice_exam.py tests/test_business_logic_bypass.py -q` -> **9 passed** (`3.14s`).

## Phase 2 — External Exams (DONE)
- **Finding #2 (Confirmed — Bulk & Single Restore Terminal Bypass)**:
  - *Root Cause*: `bulk_restore_exam_sessions` and `restore_exam_session` (`app/services/exam_service.py`) did not check `session.status`, reopening `CANCELLED` occurrences to `SCHEDULED`. `skip_exam_session`/`bulk_skip_exam_sessions` also allowed `CANCELLED -> SKIPPED`, and `session_detail.html` exposed a restore button for `CANCELLED`.
  - *Fix*: Enforced `status == "SKIPPED"` for restore, blocked `CANCELLED -> SKIPPED`, rejected/skipped archived series in restore/skip/cancel, and hid restore button for `CANCELLED` in `app/templates/tutor/exams/session_detail.html`.
- **Finding #3 (Confirmed — TOCTOU Review Lock Race)**:
  - *Root Cause*: `update_student_exam_result`, `mark_exam_result_reviewed`, `reopen_exam_result`, and `tutor_correct_exam_result` lacked row locking and session refresh (`populate_existing`), allowing concurrent student updates to overwrite a freshly reviewed/corrected result or keep stale pre-lock ORM state.
  - *Fix*: Acquire lock hierarchy `Exam (share) -> ExamSession (share) -> StudentExamResult (FOR UPDATE)` via `_lock_exam_row`/`_lock_session_row`/`_lock_result_row` and reload via `populate_existing=True` before authorization/review checks.
- **Finding #4 (Confirmed — Omitted Series Assignment Not Revoked)**:
  - *Root Cause*: `assign_exam_series_to_students` only inserted selected `student_ids` and left previously assigned omitted/unchecked students active across the series and future sessions.
  - *Fix*: Added `sync_omitted: bool = True` revocation to `assign_exam_series_to_students` (removing `ExamSeriesAssignment` and unsubmitted `ExternalExamAssignment` rows for omitted students while preserving any assignment backed by a `StudentExamResult`, logging `UNASSIGNED` audit entries) and caught `ValueError` in `post_assign_students`.
- **Finding #5 (Confirmed — Archived Series Mutations Allowed)**:
  - *Root Cause*: `update_exam`, `configure_exam_grade_track`, `delete_exam_grade_track_config`, `update_exam_session`, `generate_series_sessions`, `update_future_recurrence`, `extend_exam_recurrence`, `bulk_add_manual_sessions`, `assign_exam_series_to_students`, `assign_external_exam_to_students`, `bulk_assign_occurrences_to_students`, and session status ops lacked `exam.is_archived` (and `is_active`) checks.
  - *Fix*: Enforced `exam.is_archived` (and `not is_active` where applicable) under row locks across all configuration, schedule generation, occurrence management, and student assignment paths.
- **Finding #6 (Confirmed — Empty Effective Subject Authorization Fail-Open)**:
  - *Root Cause*: Both `submit_student_exam_result` and `update_student_exam_result` checked `(allowed_subject_ids and sub_id not in allowed_subject_ids)` and fell back to `effective_subject_ids` if `configured_subject_ids` was empty. Empty sets evaluated falsy and permitted arbitrary subjects.
  - *Fix*: Removed the truthiness gate so `sub_id not in allowed_subject_ids` fails closed (`not is_tutor_override`) and intersected against `track_config` whenever `track_config` is present.
- *Files Changed*: `app/services/exam_service.py`, `app/routers/tutor_exams.py`, `app/templates/tutor/exams/session_detail.html`, `tests/test_business_logic_bypass.py`.
- *Tests*: `tests/test_exam_service.py`, `tests/test_exam_routes.py`, `tests/test_external_and_historical_exams.py`, `tests/test_external_exam_series_workflow.py`, `tests/test_additional_requirements_workflow.py`, `tests/test_business_logic_bypass.py`, `tests/test_security_audit_regressions.py` -> **49 passed** (`13.08s`).

## Phase 3 — Study Plans & Assignments (DONE)
- **Finding #7 (Confirmed — TOCTOU Stale State / Assignment Delete Race)**:
  - *Root Cause*: `delete_assignment` fetched `PlanAssignment` without locks or refresh, allowing deletion if the student concurrently completed the assignment.
  - *Fix*: Added hierarchical locks (`StudyPlan share -> PlanAssignment FOR UPDATE`) and `.populate_existing()` via `_lock_assignment_with_plan` across `delete_assignment`, `update_assignment`, `reorder_assignment`, `complete_assignment`, `undo_assignment_completion`, and `reset_assignment_completion` (`app/services/plan_service.py`).
- **Finding #8 (False Positive — Intentional Stage-6 Feature / Spec Drift)**:
  - *Verification*: Early Stage-5 docs mentioned one-way completion, whereas Stage 6 intentionally implemented `CompletionAuditAction.STUDENT_UNDO`, `undo_assignment_completion`, `POST /student/assignments/{id}/undo`, UI undo controls, and regression test `test_undo_and_recompletion_preserves_history`. Students remain `403` blocked from tutor-only `POST /tutor/assignments/{id}/reset-completion`, and student undo requires owning `PUBLISHED` plan.
- **Finding #9 (Confirmed — Reset + Delete Erases Immutable Completion Audit History)**:
  - *Root Cause*: `PlanAssignment.completion_audits` used `cascade="all, delete-orphan"` with `ondelete="CASCADE"`, so resetting (`is_completed=False`) followed by `delete_assignment` or `delete_study_plan` destroyed all `CompletionAuditLog` records.
  - *Fix*: Changed `PlanAssignment.completion_audits` to `passive_deletes=True` and FK `CompletionAuditLog.assignment_id` to `ondelete="RESTRICT"` in `app/models/plan.py` + Alembic migration `alembic/versions/2c3d4e5f6a7b_restrict_completion_audit_assignment_delete.py`; blocked `delete_assignment` and `delete_study_plan` whenever any `CompletionAuditLog` exists.
- **Finding #10 (Confirmed — Tutor Reset Bypasses Archived Plan Immutability)**:
  - *Root Cause*: `reset_assignment_completion` did not check `PlanStatus.ARCHIVED`.
  - *Fix*: Locked assignment/plan and rejected `PlanStatus.ARCHIVED` in `reset_assignment_completion` (`app/routers/tutor.py` returns `400`).
- **Findings #11 & #12 (Confirmed — TOCTOU Complete/Undo vs Plan Archival)**:
  - *Root Cause*: `complete_assignment` and `undo_assignment_completion` locked neither `StudyPlan` nor `PlanAssignment` and `complete_assignment` checked `is_completed` before `PlanStatus.ARCHIVED`.
  - *Fix*: Acquired `StudyPlan (share) -> PlanAssignment (FOR UPDATE)` via `_lock_assignment_with_plan` (and exclusive plan lock in `archive_study_plan`), rejected `PlanStatus.ARCHIVED` before `is_completed` checks, wrapped `reorder_assignment` `PlanValidationError` -> `400` in `app/routers/tutor_plans.py`, and hid archived Undo button in `app/templates/student/partials/dashboard_task_item.html`.
- *Files Changed*: `app/models/plan.py`, `alembic/versions/2c3d4e5f6a7b_restrict_completion_audit_assignment_delete.py`, `app/services/plan_service.py`, `app/routers/tutor_plans.py`, `app/templates/student/partials/dashboard_task_item.html`, `tests/test_business_logic_bypass.py`.
- *Tests*: `.\.venv\Scripts\python.exe -m pytest tests/test_plan_service.py tests/test_stage4_planner.py tests/test_stage5_student_experience.py tests/test_grade_aware_completion_and_resources.py tests/test_business_logic_bypass.py tests/test_security_audit_regressions.py -q` -> **50 passed** (`15.50s`); `alembic heads` -> `2c3d4e5f6a7b (head)`.

## Phase 4 — Meetings (DONE)
- **Finding #13 (Confirmed — Terminal Meetings Reactivated via Reschedule / Quick-Move)**:
  - *Root Cause*: `reschedule_meeting` (`app/services/meeting_service.py`) did not check `meeting.status` before mutating time/duration, creating reschedule history, and resetting `meeting.status = MeetingStatus.SCHEDULED`. Additionally `update_meeting_status` allowed resetting back to `SCHEDULED`, `month_view.html` made terminal pills draggable, `tutor_calendar.py` (`post_edit_meeting`) referenced unimported `MeetingServiceError`, and `post_meeting_status` lacked error handling for `MeetingValidationError`/`MeetingNotFoundError`.
  - *Fix*: Used `.populate_existing()` with `.with_for_update()` on meeting mutations; rejected non-`SCHEDULED` meetings (`COMPLETED`, `CANCELLED`, `STUDENT_ABSENT`) in `reschedule_meeting` (protecting both `/reschedule` and `/quick-move`); blocked terminal -> `SCHEDULED` reactivation in `update_meeting_status`; cancelled pending reminders for all non-`SCHEDULED` statuses; handled exceptions cleanly in `tutor_calendar.py` and `tutor_scheduler.py`; removed drag attributes on terminal pills in `app/templates/tutor/calendar/partials/month_view.html`. Note transitions among non-scheduled outcomes (`STUDENT_ABSENT -> COMPLETED -> CANCELLED`) remain supported as tested in `test_meeting_status_and_cancellation`.
- *Files Changed*: `app/services/meeting_service.py`, `app/routers/tutor_calendar.py`, `app/routers/tutor_scheduler.py`, `app/templates/tutor/calendar/partials/month_view.html`, `tests/test_business_logic_bypass.py`.
- *Tests*: `.\.venv\Scripts\python.exe -m pytest tests/test_meeting_service.py tests/test_meeting_calendar_routes.py tests/test_scheduler_service.py tests/test_scheduler_routes.py tests/test_business_logic_bypass.py tests/test_security_audit_regressions.py -q` -> **50 passed** (`13.66s`).

## Phase 5 — Cross-Workflow Sibling Hardening & PostgreSQL Concurrency Tests (DONE)
- **Sibling Checkbox Revocation (`practice_exam_service.py`)**:
  - *Root Cause*: `assign_practice_exam_to_students` (`POST /tutor/practice-exams/{exam_id}/assign`, form `app/templates/tutor/practice_exams/detail.html`) only added newly checked students and silently left omitted direct assignments active, paralleling Finding #4.
  - *Fix*: Added row lock on `PracticeExam.id`, active-exam check, `sync_omitted: bool = True` revocation for omitted `PracticeExamAssignment` rows, and `populate_existing=True` support on `get_practice_exam_by_id` across locked mutations (`add_practice_exam_booklet`, `configure_practice_exam_questions`, `start_practice_attempt`, `assign_practice_exam_to_students`, `create_practice_reporting_group`).
  - *Exam Service Refresh Consistency (`exam_service.py`)*: Added `populate_existing=True` in `archive_exam` and `restore_archived_exam_series`, and `_lock_exam_row(..., share=True)` + `populate_existing=True` in `create_exam_session`.
- **PostgreSQL Integration & Concurrency Tests (`tests/test_postgres_integration.py`)**:
  - Added multi-threaded PostgreSQL tests using `threading.Barrier` (`test_postgres_concurrent_booklet_add_vs_attempt_start`, `test_postgres_concurrent_exam_review_vs_student_update`, `test_postgres_concurrent_plan_races_and_audit_restrict`) verifying row locks and native PostgreSQL FK `RESTRICT` enforcement (all skipped cleanly when local PostgreSQL is offline).
- *Tests*: `.\.venv\Scripts\python.exe -m pytest tests/test_business_logic_bypass.py -v` -> **13 passed** (`4.14s`).

## Phase 6 — Final Verification (DONE)
- **Full Test Suite (`.\.venv\Scripts\python.exe -m pytest -rs -q`)**: **219 passed, 5 skipped, 1 failed** (`65.36s`):
  - **219 passed**: All unit, workflow, route, security audit regression (`test_security_audit_regressions.py`), and business logic bypass regression (`tests/test_business_logic_bypass.py`, 13/13) tests passed against SQLite / FastAPI `TestClient`.
  - **5 skipped**: `tests/test_postgres_integration.py` (all 5 tests skipped because PostgreSQL at `localhost:15432` was not reachable).
  - **1 failed (environment-dependent pre-existing script test)**: `tests/test_demo_generator.py::test_demo_generator_and_cleanup_lifecycle` failed with `psycopg2.OperationalError: connection to server at "localhost" (127.0.0.1), port 15432 failed: Connection refused` because it connects directly to PostgreSQL via `SessionLocal()`.
- **Static & Environment Checks**:
  - `.\.venv\Scripts\python.exe -m compileall -q app tests` -> exit code `0`.
  - `.\.venv\Scripts\python.exe -m alembic heads` -> `2c3d4e5f6a7b (head)`.
  - `.\.venv\Scripts\python.exe -m pip check` -> `No broken requirements found.`

