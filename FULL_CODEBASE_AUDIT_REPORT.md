# Valhalla Tutor — Full Codebase Production & Security Audit Report

**Audit Date:** 2026-11-27  
**Auditor Role:** Independent Senior Security, Reliability, Database & Production Engineer  
**Audit Scope:** Full read-only codebase, configuration, database, frontend, infrastructure, backup/recovery, and test-suite audit (latest inspected commit: `b9e161e`)  
**Target Production Workload:** Single tutor, up to 100 students, Ubuntu VPS (2 vCPU cores, 4 GB RAM), Docker Compose, PostgreSQL 16, FastAPI, SQLAlchemy 2.0, Jinja2 + HTMX, Nginx reverse proxy  

---

## 1. Executive Summary

Valhalla Tutor is a well-structured, feature-rich server-rendered academic coaching platform (study plans, curriculum tracking, external exam series, timed multi-booklet practice exams, historical exams, calendar/meetings, semi-automatic weekly scheduler, private student-tutor messaging, bilingual EN/FA RTL/LTR UI, and backup tooling). Compared to typical MVP codebases, it demonstrates **above-average defensive engineering in its security and concurrency core**: Argon2id password hashing, SHA-256-hashed opaque server-side sessions with fixed 14-day non-rolling lifetime, consistent CSRF verification, role/ownership isolation across routers and services, magic-byte + path-traversal-hardened file storage, parameterized SQLAlchemy 2.0 queries, and PostgreSQL row-level locking on several critical workflows.

**However, the current codebase is not yet safe for unattended production launch without targeted fixes.** Seven blocking **HIGH** issues (plus one high-priority scalability issue) remain:

1. An unhandled `NameError` (`Subject` not imported) in `app/routers/tutor_exams.py` causes an HTTP 500 crash during exam grade/track configuration if any group title is empty.
2. Web-triggered and scheduled Telegram backups (`create_and_deliver_manual_backup`) transmit **unencrypted** full database dumps and student file archives to Telegram servers, contradicting the UI ("Configure encrypted database & upload delivery") and runbook documentation.
3. The scheduled Telegram backup ticker uses a session-level PostgreSQL advisory lock on a pooled connection without rolling back failed transactions before `pg_advisory_unlock`, allowing a single error to permanently wedge scheduled backups across all workers until restart.
4. External exam series analytics, session comparisons, and student comprehensive analytics silently ignore `StudentExamSubjectResult` rows when `group_results` is absent, and student comparison grade filtering fails on all UI-created students (`"10"`/`"11"`/`"12"` vs `"دهم"`/`"یازدهم"`/`"دوازدهم"`).
5. `safe_delete_exam_series` immediately destroys its own `DELETED` audit record (and prior audit logs) via `ON DELETE CASCADE` on `exam_audit_logs.exam_id`, and exam series/session deletions lack row-level locks.
6. The application boots in `ENVIRONMENT=production` with the default git-tracked `SECRET_KEY` without failing closed, weakened further because `.env` in the workspace contains development defaults (`DEBUG=True`, `POSTGRES_PASSWORD=postgres`).
7. The UI hard-depends at runtime on external unpinned CDNs without Subresource Integrity (`cdn.tailwindcss.com` Play CDN, `unpkg.com`, `cdn.jsdelivr.net`) paired with an `'unsafe-inline' 'unsafe-eval'` Content Security Policy—a critical availability hazard for students in Iran (`Asia/Tehran`) if any CDN is blocked or throttled.
8. Several core student/tutor endpoints eagerly load all students' results/attempts (`get_student_available_exams`, `get_student_available_practice_exams`) or run N+1 queries (`list_tutor_conversations` every 15s, `get_all_series_incompatible_students`), creating unnecessary latency under peak 50-student concurrency.

**Bottom line on architecture and VPS sizing:** No architectural redesign is needed. Once the production blockers above are resolved (plus static local bundling of CSS/JS/HTMX/Chart.js and minor Nginx rate-limit/timeout adjustments), a **2-core / 4 GB RAM Ubuntu VPS running Docker Compose + PostgreSQL 16 + Uvicorn (2 workers) + Nginx is sufficient** for 1 tutor and 100 students.

---

## 2. Final Production Readiness Verdict

**Verdict:** **`Not production-ready — moderate work required.`**

- **Overall Production Readiness Score:** **6.5 / 10**
- **Confidence Level in Assessment:** **High** (100% of backend routers, services, models, Alembic migrations, configuration, infrastructure/backup scripts, documentation, and key frontend/test modules were read directly; all 174 non-`TestClient` unit/service/handler tests passed (`0` failures) in the local sandbox; exact runtime limits of the Windows sandboxed test run are documented transparently in Sections 4 and 16).
- **Can 1 tutor and 100 students safely use this exact codebase today?** **No.** Must resolve the 7 blocking **HIGH** issues (`HIGH-01` through `HIGH-07`), ideally alongside `HIGH-08` and Nginx classroom NAT tuning (`MED-03`), and verify the full `TestClient` + `test_postgres_integration.py` suite on Linux/Docker PostgreSQL 16 via `scripts/run_docker_tests.sh`.
- **Are 2 CPU cores and 4 GB RAM sufficient?** **Yes**, once N+1 / unbounded queries (`HIGH-08`) and runtime Tailwind Play CDN overhead (`HIGH-07`) are addressed.
- **Exact blockers preventing production launch:** `HIGH-01`, `HIGH-02`, `HIGH-03`, `HIGH-04`, `HIGH-05`, `HIGH-06`, `HIGH-07` (and `run_docker_tests.sh` PostgreSQL 16 verification before go-live).

---

## 3. Score Table

| Area | Score | Key Rationale |
|---|---:|---|
| Functional correctness | **6.5 / 10** | Core workflows are rich and cohesive, but `NameError` 500 in `tutor_exams.py`, dropped subject-based exam analytics, broken compare grade filter, and missing practice exam edit/delete/0-question guards hurt reliability. |
| Security | **6.5 / 10** | Strong Argon2id/session/CSRF/IDOR/upload validation core, undermined by unencrypted Telegram backups, no production startup check on `SECRET_KEY`, unpinned external CDNs + `'unsafe-eval'`/`'unsafe-inline'` CSP, case-sensitive/timing-leaky login, and weak password checks. |
| Business logic integrity | **7.0 / 10** | Strong plan/attempt/meeting locks and ownership validation; weakened by `ExamAuditLog` cascade self-deletion, missing row locks on exam deletion, `CANCELLED<->COMPLETED` meeting jumps, scheduler item mutation before `proposal_id` check, and spec drift on student undo. |
| Database integrity | **7.5 / 10** | Clean SQLAlchemy 2.0 relational model, composite `(id, student_id)` FK, partial unique published-plan index, 21 clean Alembic migrations; gaps in active practice-attempt partial unique index, check constraints on scores, and `CASCADE` vs `RESTRICT` edges. |
| Performance | **6.0 / 10** | Synchronous threadpool architecture fits 100 users well, but loading all students' exam results/attempts per student request, `2N+1` inbox queries on 15s polling, `/tutor/exams` N+1, duplicate unread pollers, and runtime Tailwind Play CDN waste CPU. |
| Frontend reliability | **6.0 / 10** | Responsive RTL/LTR Persian UI, Jalali formatting, and safe DOM in `runner.html`; hurt by external CDN reliance without fallback, 4 broken multiline `_()` keys, EN/FA swap on historical report card link, search reset during inbox poll, 15MB UI vs 10MB backend mismatch. |
| Infrastructure | **6.5 / 10** | Non-root Dockerfile, healthchecks, memory limits, loopback port binding; gaps in `SECRET_KEY` fail-closed check, double migration execution (`manage.sh` while old container runs + `entrypoint.sh`), Nginx `5r/m` blocking shared-NAT login GETs, leftover test PDFs in `uploads/`. |
| Backup and recovery | **5.5 / 10** | CLI `backup.sh`/`restore.sh` are strong (manifest, checksums, `pg_restore --list`, `--dry-run`), but web/scheduled Telegram backups send unencrypted DB dumps while claiming encryption, advisory lock leak can halt backups, and no tested restore drill is evidenced. |
| Maintainability | **7.0 / 10** | Clean modular router/service/model layout and localized error mapping in newer modules; weighed down by 3,186-line `exam_service.py` monolith, `LegacyAPIWarning` `.get()` calls, 26 leftover translation/demo scripts in `scripts/`, and stale architecture docs. |
| Test coverage and confidence | **6.5 / 10** | Strong 277-test suite with concurrency & bypass regressions; reduced confidence because `TestClient` blocked in Windows sandbox, PostgreSQL tests weren't run locally, `test_demo_generator.py` writes to `SessionLocal()`, `test_practice_exam.py` leaks PDFs into `uploads/`, and multiline `_()` regex missed broken translations. |
| **Overall production readiness** | **6.5 / 10** | Unweighted mean of all 10 dimensions; verdict is **Not production-ready — moderate work required.** |

---

## 4. Repository Inspection Coverage

Total workspace files inventoried (excluding `.git`, `.venv`, `__pycache__`, `.pytest_cache`): **287 files** (including 1 empty/artifact folder marker set and 2 leftover test PDFs in `uploads/`).

| Repository Area | Count | Coverage Status | Inspection Details |
|---|---:|---|---|
| Root config, infra, Docker & Nginx | 13 files | **Fully Inspected (100%)** | `.env`, `.env.example`, `.dockerignore`, `.gitignore`, `Dockerfile`, `docker-compose.yml`, `docker-compose.dev.yml`, `nginx/valhalla.conf`, `requirements.txt`, `pyproject.toml`, `alembic.ini`, `README.md`, `LICENSE` |
| Documentation (`docs/`) | 8 files | **Fully Inspected (100%)** | `ARCHITECTURE.md`, `AUTHORIZATION.md`, `BACKUP_AND_RESTORE.md`, `DATABASE.md`, `DEPLOYMENT.md`, `IMPLEMENTATION_PLAN.md`, `PERSIAN_REDESIGN_PROGRESS.md`, `PRODUCT_SPEC.md` |
| Core app (`app/main.py`, `app/cli.py`, `app/core/`, `app/schemas/`) | 14 files | **Fully Inspected (100%)** | `main.py`, `cli.py`, `schemas/health.py`, `core/{config,database,dependencies,security,rate_limit,storage,templates,timezone,i18n}.py` |
| Models (`app/models/`) | 14 files | **Fully Inspected (100%)** | `__init__.py`, `base.py`, `user.py`, `session.py`, `subject.py`, `track.py`, `book.py`, `course.py`, `plan.py`, `exam.py`, `practice_exam.py`, `meeting.py`, `message.py`, `settings.py` |
| Migrations (`alembic/`) | 24 files | **Fully Inspected (100%)** | `env.py`, `script.py.mako`, `README`, all 21 revision files (`9c005c0812c7` -> `4e5f6a7b8c9d`) |
| Routers (`app/routers/`) | 21 files | **Fully Inspected (100%)** | `__init__.py` + all 20 route modules (`auth`, `health`, `student*`, `tutor*`) |
| Services (`app/services/`) | 13 files | **Fully Inspected (100%)** | `__init__.py` + all 12 service modules (`academic`, `auth`, `exam`, `meeting`, `message`, `plan`, `practice_exam`, `resource`, `scheduler`, `telegram_backup`, `tutor_provision`, `user`) |
| Static JS/CSS & Locales (`app/static/`, `app/locales/`) | 6 files | **Fully Inspected / Parity Verified (100%)** | `i18n.js` & `persian-ui.css` read in full; `en.json` & `fa.json` (2,260 keys each) programmatically audited for key parity, blanks, placeholders, and untranslated entries |
| HTML Templates (`app/templates/`) | 82 files | **Partially Read / Full Automated Scan** | 81 `.html` files + `.gitkeep`. Key pages/partials (~33 templates) read line-by-line; all 81 templates programmatically audited for CSRF inputs, `| safe`, `innerHTML`, upload size text, grade constants, `_()` / `vt()` keys, and HTMX patterns |
| Operational, Demo & i18n Scripts (`scripts/`) | 39 files | **Operational & Demo Core Read; Helper Scripts Inventoried** | `entrypoint.sh`, `backup.sh`, `restore.sh`, `manage.sh`, `run_docker_tests.sh`, `generate_demo_data.py`, `demo_cleanup.py`, `test_html_localizer.py`, `test_templates_localization.py`, `verify_persian_pages.py` read in full; 26 historical `build_complete_fa_catalog*`/`add_*`/`extract_*` i18n build scripts and 8 demo seeders inventoried but not reviewed line-by-line |
| Tests (`tests/`) | 46 files | **High Coverage Inspected; Partial Execution** | `conftest.py` + 25 major test modules read fully or in critical sections; 277 tests collected; **174 non-`TestClient` unit/service/handler tests passed (`0` failures, `27` warnings)**; `97` `TestClient` tests, `test_postgres_integration.py` (`5`), and `test_demo_generator.py` (`1`) not executed locally (reasons in Section 16) |
| Runtime Upload Artifacts (`uploads/`) | 2 files | **Inspected (Metadata)** | `uploads/practice_booklets/dl_test_b1.pdf`, `dl_test_b2.pdf` (23 bytes each; leftover test files) |
| Installed Packages (`.venv`) | — | **Checked** | `pip list` verified exact versions matching `requirements.txt` (excluded third-party source from review) |

---

## 5. Critical Findings

**0 Critical findings confirmed.**

*Calibration note:* No unauthenticated remote code execution, SQL injection, arbitrary file read/write traversal, authentication bypass, or exploitable cross-student IDOR was found. Finding `HIGH-02` (unencrypted off-site Telegram backups) has severe confidentiality implications if enabled by the tutor and is flagged as a mandatory launch blocker under **High Findings** because Telegram delivery is optional, disabled by default, requires tutor credentials, and transmits to a tutor-controlled bot/chat over TLS.

---

## 6. High Findings

### HIGH-01 — Unhandled `NameError` (`Subject` Not Imported) Crashes Exam Grade/Track Configuration
- **Severity:** HIGH  
- **Category:** Functional Bug / Backend Crash  
- **Exact File Path:** `app/routers/tutor_exams.py`  
- **Relevant Function / Lines:** `post_configure_grade_track` (`lines 370-374`, imports `lines 1-65`)  
- **Evidence:**  
  ```python
  # app/routers/tutor_exams.py:371-374
  grp_name = str(form_data.get(f"subject_group_{sid}", "")).strip()
  if not grp_name:
      sub = db.query(Subject).filter(Subject.id == sid).first()
      grp_name = sub.name if sub else str(sid)
  ```
  `Subject` is never imported anywhere in `app/routers/tutor_exams.py`.
- **Explanation:** When configuring an exam's grade/track reporting structure, if the tutor leaves or clears the group name input for any selected subject, `post_configure_grade_track` attempts to fall back to `db.query(Subject)`, raising `NameError: name 'Subject' is not defined` (HTTP 500).
- **Exploitation / Failure Scenario:** A tutor sets up an exam grade/track structure (`tutor/exams/configure_grade_track.html`), clears a group input to use the subject's default name, submits the form, and receives an unhandled HTTP 500 error with failed transaction.
- **Actual Impact:** Blocks configuring exam grade/track structures whenever a group name is left blank.
- **Recommended Fix:** Import `Subject` from `app.models.subject` (or resolve subject names cleanly via `track.subjects` already loaded in memory). Add a regression test in `tests/test_exam_routes.py`.
- **Estimated Complexity:** Easy  
- **Blocks Initial Production:** **Yes**

---

### HIGH-02 — Unencrypted Student Database & Uploads Sent to Telegram Despite UI Claiming Encryption
- **Severity:** HIGH  
- **Category:** Data Confidentiality / Security / Backup Integrity  
- **Exact File Path:** `app/services/telegram_backup_service.py`, `app/templates/tutor/settings/backup.html`, `docs/BACKUP_AND_RESTORE.md`, `scripts/backup.sh`  
- **Relevant Function / Configuration:** `create_and_deliver_manual_backup` (`telegram_backup_service.py:553-640`), `backup.html:10`  
- **Evidence:**  
  - `app/templates/tutor/settings/backup.html:10`: `"Configure encrypted database & upload delivery to a Telegram chat or channel."`  
  - `docs/BACKUP_AND_RESTORE.md:85`: instructs restoring Telegram downloads named `valhalla_backup_<TIMESTAMP>.tar.gz.enc`.  
  - `app/services/telegram_backup_service.py:629-639`: creates `bundle_path = tmp_dir / f"valhalla_backup_{ts}.tar.gz"` containing plaintext `db.dump` (or `db_export.json.gz`) and `uploads.tar.gz`, and uploads it directly via `deliver_backup_to_telegram(...)` with **zero client-side encryption**.  
  - `scripts/backup.sh:13,103+` defaults `ENCRYPT_MODE="auto"`, so if `BACKUP_ENCRYPTION_KEY` / `--passphrase-file` is omitted, cron backups are also uploaded unencrypted.
- **Explanation:** Telegram chats and bots are not end-to-end encrypted. Every automated or manual backup triggered from `/tutor/settings/backup` transmits plaintext student PII (names, emails, grades), Argon2id password hashes, active `user_sessions` (token hashes and CSRF tokens), private tutor-student chat logs, exam scores, and uploaded report card files onto Telegram infrastructure.
- **Exploitation / Failure Scenario:** Tutor enables Telegram backups trusting the UI label ("encrypted database & upload delivery"). Compromise of the bot token, Telegram account, channel invite, or server-side Telegram bot storage exposes the entire database and file archive in cleartext.
- **Actual Impact:** Complete student/tutor PII and academic dataset disclosure without an encryption passphrase barrier.
- **Recommended Fix:** Encrypt Telegram backup bundles before upload inside `create_and_deliver_manual_backup` (and enforce mandatory encryption whenever delivering off-site via Telegram, using an operator-configured `BACKUP_ENCRYPTION_KEY` / dedicated passphrase—never `SECRET_KEY` alone unless clearly documented, since `SECRET_KEY` is in `.env` on the same VPS—and verify `restore.sh` can decrypt `.enc` parts cleanly). Remove misleading "encrypted" UI copy unless encryption actually occurs.
- **Estimated Complexity:** Moderate  
- **Blocks Initial Production:** **Yes**

---

### HIGH-03 — Scheduled Backup Advisory Lock Leak & Multi-Worker Race Condition
- **Severity:** HIGH  
- **Category:** Reliability / Concurrency / Backup Automation  
- **Exact File Path:** `app/services/telegram_backup_service.py`, `app/main.py`  
- **Relevant Function / Lines:** `run_scheduled_backup_tick` (`telegram_backup_service.py:642-715`), `_telegram_backup_scheduler_loop` (`main.py:38-55`)  
- **Evidence:**  
  1. `run_scheduled_backup_tick` (`lines 652-661`) reads `get_or_create_telegram_settings(db)` and updates/commits `next_run_at` **before** acquiring `_SCHEDULER_ADVISORY_LOCK_ID` (`88421001`).  
  2. Lines 669-714 acquire session-level `pg_try_advisory_lock` on the pooled `Session` `db`. Inside `finally:` (lines 707-714):
     ```python
     try:
         db.execute(text("SELECT pg_advisory_unlock(:lock_id)"), ...)
     except Exception:
         pass
     ```
     There is **no `db.rollback()`** prior to `pg_advisory_unlock`.  
  3. `app/main.py:46-59` spawns `_telegram_backup_scheduler_loop()` inside **each** Uvicorn worker (`WEB_CONCURRENCY=2`), running heavy synchronous `pg_dump` + `tar` + multi-part uploads inside the web worker's threadpool.
- **Explanation:** If `create_and_deliver_manual_backup`, `_record_status`, or the `finally:` commit on line 703 raises a database error (`IntegrityError`, timeout, connection drop), SQLAlchemy leaves `db` in `InFailedSqlTransaction`. PostgreSQL rejects `SELECT pg_advisory_unlock(...)` inside an aborted transaction, the bare `except Exception: pass` swallows the failure, and `with SessionLocal() as db:` returns the connection to SQLAlchemy's queue pool **while still holding the PostgreSQL session-level advisory lock**. Until that exact pooled backend connection closes/recycles (`1800s` or restart), every 60s tick across all workers sees `pg_try_advisory_lock` return `False`.
- **Exploitation / Failure Scenario:** A transient DB timeout during scheduled backup fails line 703 `db.commit()`, leaves the advisory lock wedged on pooled connection #1, and silently halts all future automatic Telegram backups with zero error logged on subsequent ticks.
- **Actual Impact:** Silent total loss of automated off-site backups.
- **Recommended Fix:** Call `db.rollback()` before `pg_advisory_unlock`, use a dedicated non-pooled or explicitly invalidated connection for session-level advisory locks (or `pg_try_advisory_xact_lock` / lock before reading `next_run_at`), and guard concurrent `get_or_create_telegram_settings` creation. Ideally run scheduled backups via host cron / dedicated command rather than inside every web worker.
- **Estimated Complexity:** Easy  
- **Blocks Initial Production:** **Yes**

---

### HIGH-04 — External Exam Analytics Silently Drop Subject-Based Results & Student Comparison Grade Filter Breaks
- **Severity:** HIGH  
- **Category:** Business Logic Error / Functional Bug  
- **Exact File Path:** `app/services/exam_service.py`, `app/templates/tutor/exams/compare_students.html`  
- **Relevant Functions / Lines:** `compare_students_on_session` (`exam_service.py:2895-2969`), `get_exam_series_analytics` (`3021-3065`), `get_student_comprehensive_analytics` (`3067-3130`), `compare_students.html:22-24`  
- **Evidence:**  
  - `compare_students_on_session` (`lines 2923-2929`), `get_exam_series_analytics` (`lines 3027-3045`), and `get_student_comprehensive_analytics` (`lines 3100-3110`) read **only** `r.group_results` (`StudentExamGroupResult`) and never fall back to `r.subject_results` (`StudentExamSubjectResult`).  
  - `compare_students.html:22-24` sends `<option value="دهم">`, `<option value="یازدهم">`, `<option value="دوازدهم">`, whereas `tutor/students/create.html`, `tutor/students/detail.html`, and `user_service.update_student_grade` store `"10"`, `"11"`, `"12"`. Yet `compare_students_on_session` (`line 2908`) checks `a.student.grade == str(grade)` without using the grade alias normalization map present elsewhere in `exam_service.py:2269-2274`.
- **Explanation:** Any external exam session submitted without Reporting Groups (standard per-subject entry) shows `0.0%` series averages, `None` student averages, empty breakdowns, and missing trend diffs in tutor comparison and series/comprehensive analytics. Furthermore, filtering session comparisons by Grade 10/11/12 always returns **0 students** for all accounts created via the UI.
- **Exploitation / Failure Scenario:** Tutor schedules an exam session without reporting groups (or clicks a grade filter on `/tutor/exams/sessions/{id}/compare`). All submitted student scores show "No score submitted" / `0.0%`, or the entire table appears empty.
- **Actual Impact:** Major core tutoring analytics and student group comparisons fail silently in real usage.
- **Recommended Fix:** Fall back to `r.subject_results` (`sr.subject_name` -> `sr.percentage`) whenever `r.group_results` is empty across all three analytics functions, and normalize `grade` filters in `compare_students_on_session` (and submit `"10"`/`"11"`/`"12"` in `compare_students.html`).
- **Estimated Complexity:** Easy  
- **Blocks Initial Production:** **Yes**

---

### HIGH-05 — Exam Series Deletion Destroys Its Own Audit Trail via `CASCADE` & Lacks Row Locking
- **Severity:** HIGH  
- **Category:** Data Integrity / Auditability / Concurrency  
- **Exact File Path:** `app/services/exam_service.py`, `app/models/exam.py`  
- **Relevant Functions / Lines:** `safe_delete_exam_series` (`exam_service.py:364-386`), `delete_exam_session` (`792-818`), `ExamAuditLog.exam_id` (`models/exam.py:665-670`), `Exam.audit_logs`  
- **Evidence:**  
  ```python
  # app/services/exam_service.py:376-386
  log_exam_audit(..., entity_type="SERIES", entity_id=exam.id, action="DELETED", exam_id=exam.id, ...)
  db.delete(exam)
  db.commit()
  ```
  `ExamAuditLog.exam_id` is defined with `ForeignKey("exams.id", ondelete="CASCADE")` (`app/models/exam.py:667`) and `cascade="all, delete-orphan"` on `Exam`. Neither `safe_delete_exam_series` nor `delete_exam_session` locks rows with `.with_for_update()`.
- **Explanation:** Immediately after inserting the `DELETED` audit entry referencing `exam.id`, `db.delete(exam)` triggers ORM and PostgreSQL `ON DELETE CASCADE`, **wiping the `DELETED` audit row and every historical audit entry for that exam series**. Additionally, checking `any(len(s.results) > 0 ...)` without locking allows a concurrent student result submission during deletion to either vanish or cause integrity errors.
- **Exploitation / Failure Scenario:** Tutor deletes an exam series (even one previously edited/assigned), expecting a permanent audit trail. All audit records for that series vanish at commit. Concurrently, a student submitting a result while a session/series is deleted can race the un-locked check.
- **Actual Impact:** Loss of audit history and TOCTOU race during exam/session deletion.
- **Recommended Fix:** Change `ExamAuditLog.exam_id` FK to `ondelete="SET NULL"` (preserving immutable historical series deletion logs, matching how `completion_audit_logs` protects task history), remove delete cascade from `Exam.audit_logs`, detach `exam_id=None` or let PostgreSQL set it `NULL` on delete, and acquire `.with_for_update()` row locks on `Exam` / `ExamSession` before checking results.
- **Estimated Complexity:** Moderate  
- **Blocks Initial Production:** **Yes**

---

### HIGH-06 — Production Boots With Default Git-Tracked `SECRET_KEY` Without Startup Validation
- **Severity:** HIGH  
- **Category:** Configuration & Secrets Security  
- **Exact File Path:** `app/core/config.py`, `app/main.py`, `.env`, `.env.example`  
- **Relevant Configuration / Lines:** `Settings.SECRET_KEY` (`config.py:32`), `main.py:70-80`, `.env:17,21`  
- **Evidence:**  
  - `app/core/config.py:32`: `SECRET_KEY: str = "dev-secret-key-please-change-in-production-min-32-chars"`  
  - `app/main.py:70-80`: inspects `ENVIRONMENT == "production"` only to hide Swagger docs and disable `DEBUG`; performs zero startup checks rejecting known default/placeholder `SECRET_KEY` or `POSTGRES_PASSWORD`.  
  - Workspace `.env` contains `ENVIRONMENT=development`, `DEBUG=True`, `POSTGRES_PASSWORD=postgres`, and the default `SECRET_KEY`.
- **Explanation:** While `.dockerignore` rightly excludes `.env` from Docker image layers, Docker Compose reads host `.env` directly at container startup. Without fail-closed startup validation, forgetting to rotate `SECRET_KEY` or copying `.env` / `.env.example` placeholder values leaves production running silently with a public key from source code (which derives the HMAC/CTR key for `telegram_backup_settings.encrypted_bot_token` in `telegram_backup_service.py:132-141`).
- **Exploitation / Failure Scenario:** Operator copies `.env` to VPS changing only `ENVIRONMENT=production` (or forgets `SECRET_KEY` / leaves `.env.example` placeholder). Any leak of DB backups or `telegram_backup_settings` allows instant offline decryption of the Telegram Bot Token.
- **Actual Impact:** Weakened secret protection for Telegram Bot integration credentials in production.
- **Recommended Fix:** Add a fail-closed startup validator in `app/core/config.py` or `app/main.py` when `ENVIRONMENT.lower() == "production"` rejecting missing/short (`<32` chars) or known default/placeholder `SECRET_KEY` and weak default `POSTGRES_PASSWORD=postgres`.
- **Estimated Complexity:** Very easy  
- **Blocks Initial Production:** **Yes**

---

### HIGH-07 — External Unpinned CDNs Without SRI + `'unsafe-inline' 'unsafe-eval'` CSP (Iran Availability & XSS Risk)
- **Severity:** HIGH  
- **Category:** Frontend Reliability / Web Security  
- **Exact File Path:** `app/templates/base.html`, `app/templates/student/exams/analytics.html`, `app/templates/tutor/exams/student_analytics.html`, `app/main.py`  
- **Relevant Lines:** `base.html:9-10`, `student/exams/analytics.html:150`, `tutor/exams/student_analytics.html:144`, `main.py:105-117`  
- **Evidence:**  
  - `base.html:9`: `<script src="https://cdn.tailwindcss.com"></script>` (runtime JIT Tailwind Play CDN—requires `'unsafe-eval'`/`'unsafe-inline'`, slower mobile parsing, never intended for production).  
  - `base.html:10`: `<script src="https://unpkg.com/htmx.org@1.9.12"></script>` (no `integrity=` attribute).  
  - `analytics.html:150` / `student_analytics.html:144`: `<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>` (unpinned floating version, no SRI).  
  - `main.py:107`: `script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://unpkg.com https://cdn.jsdelivr.net;`
- **Explanation:** First, students and the tutor primarily connect from `Asia/Tehran`, where external CDNs (`cdn.tailwindcss.com`, `unpkg.com`, `cdn.jsdelivr.net`) are frequently rate-limited, DNS-filtered, or slow. If `cdn.tailwindcss.com` or `unpkg.com` fails to load, the entire application loses all CSS styling and HTMX interactivity (completing tasks, chat polling, modals). Second, `'unsafe-inline' 'unsafe-eval'` weakens XSS defense-in-depth, and unpinned `chart.js` without SRI exposes browsers to upstream supply-chain tampering.
- **Exploitation / Failure Scenario:** Student opens the app during ISP throttling on `cdn.tailwindcss.com`/`unpkg.com`; pages render unstyled broken HTML and "Mark Complete" HTMX buttons silently do nothing.
- **Actual Impact:** Application outage/unusable UX for real Iranian users and weakened CSP posture.
- **Recommended Fix:** Pre-build Tailwind CSS into `app/static/css/tailwind.css` during Docker build or repo commit, vendor pinned local copies of `htmx.min.js` and `chart.umd.min.js` under `app/static/js/`, remove `'unsafe-eval'` and third-party CDN hosts from CSP in `app/main.py`, and gradually migrate inline `<script>` / `onclick` handlers so `'unsafe-inline'` can be removed or nonce-gated.
- **Estimated Complexity:** Moderate  
- **Blocks Initial Production:** **Yes**

---

### HIGH-08 — Unbounded Cross-Student Eager Loading & N+1 Query Hotspots Under Peak Concurrency
- **Severity:** HIGH  
- **Category:** Performance & Scalability  
- **Exact File Path:** `app/services/exam_service.py`, `app/services/practice_exam_service.py`, `app/services/message_service.py`, `app/templates/base.html`  
- **Relevant Functions / Lines:** `get_student_available_exams` (`exam_service.py:1273-1328`), `get_student_available_practice_exams` (`practice_exam_service.py:320-345`), `get_all_series_incompatible_students` (`exam_service.py:2582-2609`), `list_tutor_conversations` (`message_service.py:315-339`), `base.html:238,314`, `mobile_nav_drawer.html:55,156`  
- **Evidence:**  
  - `get_student_available_exams`: executes `ExamSession` query with `joinedload(ExamSession.results)` **without filtering `results` by `student_id`**, hydrating every student's `StudentExamResult` rows across all sessions and calling `get_student_series_grade_track_config` per session in a Python loop (`N+1`).  
  - `get_student_available_practice_exams`: `joinedload(PracticeExam.attempts)` loads all students' attempts, and `any(a.student_id == student.id for a in exam.assignments)` triggers N+1 lazy-loads per exam.  
  - `get_all_series_incompatible_students` (run on every `GET /tutor/exams`): issues N+1 DB queries across every `ExamSeriesAssignment`.  
  - `list_tutor_conversations`: executes `2N + 1` queries (`latest_msg` + `unread_count` per student, ~201 SQL queries for 100 students) on `/tutor/messages` and every 15s poll (`/tutor/messages/conversations`). Meanwhile `base.html` renders **two** desktop+mobile unread pollers plus two hidden drawer pollers per page (`every 15s`), doubling background polling queries per open tab.
- **Explanation:** Under peak usage (e.g., 50 students checking `/student/exams` or `/student/practice-exams` after a mock exam, plus tutor managing `/tutor/messages` and `/tutor/exams`), Python ORM hydration of O(`exams × students`) rows and hundreds of N+1 round-trips consume excessive CPU and connection pool time on a 2-core VPS.
- **Exploitation / Failure Scenario:** 50 students open `/student/exams` right after results open; with 30 sessions and 100 students, each request hydrates up to ~3,000 result objects + N+1 config queries, saturating the 2 Uvicorn workers' CPU and causing latency spikes.
- **Actual Impact:** Significant latency degradation during realistic 50-student peak bursts (and high background DB churn from tutor inbox polling).
- **Recommended Fix:** Query only `student_id == student.id` results/attempts in separate indexed queries (or `contains_eager` with filtered outer joins), replace `2N+1` inbox loops with correlated/window subqueries, cache or batch `get_all_series_incompatible_students`, and use one responsive unread poller per page.
- **Estimated Complexity:** Moderate  
- **Blocks Initial Production:** **No** *(Non-crashing at low scale, but high-priority fix before exam-night bursts of 25–50 simultaneous students)*

---

## 7. Medium Findings

### MED-01 — Potential PostgreSQL Deadlock via Inconsistent Lock Ordering in `publish_study_plan`
- **Severity:** MEDIUM  
- **Category:** Concurrency / Database Integrity  
- **File & Symbol:** `app/services/plan_service.py` — `publish_study_plan` (`lines 401-435`)  
- **Evidence:** Acquires `FOR SHARE` on `StudyPlan` (`line 403`), then `FOR UPDATE` on `User` (`line 410`), then `FOR UPDATE` on existing `StudyPlan` rows (`line 428`). Meanwhile `delete_study_plan` (`lines 455+`) and `_lock_assignment_with_plan` (`lines 316-335`) lock `StudyPlan` first, and upgrading `FOR SHARE` to `FOR UPDATE` on the same `StudyPlan` or racing two concurrent `publish_study_plan` calls for two drafts of the same student (`plan_A` and `plan_B`) reverses lock order (`plan_A -> user -> plan_B` vs `plan_B -> user -> plan_A`).  
- **Explanation & Impact:** Under double-click or concurrent tutor tabs publishing different drafts for the same student, PostgreSQL can detect a lock cycle and abort one request with `DeadlockDetected` (HTTP 500).  
- **Recommended Fix:** Look up `student_id` without a lock first, acquire `FOR UPDATE` on `User` **before** locking any `StudyPlan` rows (`User -> StudyPlan` ordered by `StudyPlan.id`).  
- **Complexity:** Easy | **Blocks Prod:** No

### MED-02 — Case-Sensitive Login Mismatch, Argon2 Timing Side-Channel & No Password Policy
- **Severity:** MEDIUM  
- **Category:** Authentication Security  
- **File & Symbol:** `app/services/auth_service.py` (`authenticate_user`, `lines 20-34`), `app/services/user_service.py` (`create_student`, `reset_student_password`, `lines 37-100`), `app/routers/tutor.py`  
- **Evidence:** `create_student` lowercases usernames/emails (`lines 47-48`), whereas `authenticate_user` queries `or_(User.username == cleaned, User.email == cleaned)` **without `.lower()`**. Furthermore, `authenticate_user` returns `None` immediately when user is missing/inactive without running `verify_password`, and no minimum password length/strength exists (tests even create passwords like `"p"` or `"pass"`).  
- **Explanation & Impact:** Students typing `Student1` on mobile auto-capitalization fail login despite valid credentials; timing differences between instant DB miss and ~50–150ms Argon2 verification allow remote account enumeration across rate limits; weak passwords created by tutor are vulnerable to brute-force if rate-limiting is bypassed.  
- **Recommended Fix:** Lowercase `cleaned` in `authenticate_user`, run a dummy `verify_password` on unknown/inactive users to equalize response timing, and enforce a sensible minimum password length (e.g., `>= 8` chars) in `user_service` and HTML `minlength="8"`.  
- **Complexity:** Easy | **Blocks Prod:** No

### MED-03 — Nginx Rate-Limits All `/auth/login` Requests Including `GET` (Classroom NAT Lockout) & Omitted Location Timeouts
- **Severity:** MEDIUM  
- **Category:** Infrastructure / Nginx Configuration  
- **File & Symbol:** `nginx/valhalla.conf` (`lines 1-106`, specifically `lines 2, 16, 34-35, 57-86, 102-104`)  
- **Evidence:** `limit_req zone=valhalla_auth burst=10 nodelay;` (`rate=5r/m`) applies to all methods on `/auth/login` (not just `POST`). Timeouts (`proxy_connect_timeout`, `proxy_read_timeout`, `proxy_send_timeout`) are configured only in `location /` (`lines 102-104`), omitted in `location /auth/login` and `location ~ ^/(student/chat|tutor/messages)`. Placeholder `your-domain.com` appears verbatim in lines 16, 31, 34, 35.  
- **Explanation & Impact:** If 15 students in the same school/coaching institute open `/auth/login` behind one shared NAT IP within 1 minute (`15 GET` + `15 POST` = 30 requests), Nginx returns `429 Too Many Requests` (`burst=10`, `5r/m`) even for legitimate logins, whereas FastAPI's `login_limiter` already safely throttles failed `POST` logins only. Also Nginx reload fails if run before obtaining Certbot certificates because lines 34-35 reference `/etc/letsencrypt/live/your-domain.com/...`.  
- **Recommended Fix:** Restrict Nginx login `limit_req` via `limit_except GET HEAD` or higher burst (`rate=30r/m; burst=30`), rely on app `login_limiter` for brute-force protection, extract shared proxy timeout/header snippets (`include proxy_params;` / Nginx snippet), and document HTTP->Certbot bootstrap ordering in `docs/DEPLOYMENT.md`.  
- **Complexity:** Easy | **Blocks Prod:** No *(Strongly recommended before classroom/cohort usage)*

### MED-04 — IPv4-Mapped IPv6 Rate-Limit Bucket Collapse & Per-Request SQLite Connection Churn
- **Severity:** MEDIUM  
- **Category:** Backend Security / Performance  
- **File & Symbol:** `app/core/rate_limit.py` (`LoginRateLimiter._connect` `lines 37-42`, `_clean_ip_str` `lines 173-179`)  
- **Evidence:**  
  ```python
  elif ":" in raw and "." in raw:
      raw = raw.split(":")[0]
  ```
  On an IPv4-mapped IPv6 string like `::ffff:203.0.113.5`, `raw.split(":")[0]` evaluates to `""`. Meanwhile `_connect()` opens and closes a new SQLite file handle and runs `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;` and `CREATE TABLE IF NOT EXISTS` on every single `check_allowed` / `record_attempt` / `reset` call.  
- **Explanation & Impact:** On dual-stack VPS setups forwarding `::ffff:x.x.x.x`, every IPv4 client collapses into empty key `""` (allowing 5 failed logins by one attacker or 30 chat messages across the whole cohort to block everyone). Re-initializing WAL + DDL on every message/login adds avoidable disk/lock overhead under concurrent load.  
- **Recommended Fix:** Use `ipaddress.ip_address(raw)` properly (falling back to bracketed port stripping only when needed) so `::ffff:x.x.x.x` maps cleanly, and run schema/WAL initialization once at startup rather than on every request.  
- **Complexity:** Easy | **Blocks Prod:** No

### MED-05 — Practice Exam Zero-Question Start, Missing Management Routes & No DB Active-Attempt Uniqueness
- **Severity:** MEDIUM  
- **Category:** Business Logic / Workflow Completeness  
- **File & Symbol:** `app/services/practice_exam_service.py` (`start_practice_attempt`, `lines 348-423`), `app/routers/tutor_practice_exams.py`, `app/models/practice_exam.py`  
- **Evidence:** `start_practice_attempt` checks `if not exam.booklets:` (`line 368`) but never checks `if not exam.questions:`. `tutor_practice_exams.py` exposes create/assign/booklet-add/group-add/question-config endpoints, with **no routes** to edit exam metadata/retake flag/timed setting, toggle `is_active`, delete a draft practice exam/booklet/group, or handle `PracticeExamAttempt` active-status uniqueness via a PostgreSQL partial unique index.  
- **Explanation & Impact:** A tutor who creates an exam and uploads booklets before entering answer keys lets students start & complete an unconfigured exam (`0.0%` permanently locking non-retake attempts); and typos or mistaken booklet uploads cannot be edited or removed in the UI.  
- **Recommended Fix:** Require `if not exam.questions:` (and check `question_start`/`question_end` question coverage) in `start_practice_attempt`, add safe edit/deactivate/delete routes (guarded when attempts exist), and add a partial unique index `uq_practice_attempts_student_exam_in_progress` on `(student_id, practice_exam_id) WHERE status = 'IN_PROGRESS'`.  
- **Complexity:** Moderate | **Blocks Prod:** No

### MED-06 — Scheduler Commits Before ID Ownership Validation, Leaves Stale Conflicts & Sends Hardcoded English Notices
- **Severity:** MEDIUM  
- **Category:** Business Logic / Localization  
- **File & Symbol:** `app/routers/tutor_scheduler.py` (`lines 310-321`), `app/services/scheduler_service.py` (`lines 456, 538-545, 593-599`)  
- **Evidence:**  
  - `tutor_scheduler.py:310-321` executes and commits `update_proposal_item(...)` **before** checking `if item.proposal_id != proposal_id: raise HTTPException(404)`.  
  - `scheduler_service.py:456`: if `find_available_slot` returns `None` during `regenerate_unadjusted_items`, the item silently retains its previous conflicting `start_time_str`.  
  - Lines `538-545` and `593-599` insert English chat notifications (`"Weekly Session Scheduled..."`, `"Session Rescheduled..."`) regardless of student/tutor language preference, and `quick_move_meeting` commits `reschedule_meeting` separately from `send_message`.  
- **Recommended Fix:** Pass `proposal_id` into `update_proposal_item` and validate before mutating/committing; flag/fail unplaceable items during regeneration; localize automated chat notices based on user/app locale or structured templates; and commit `quick_move_meeting` + notification atomically (`commit=False` on inner helpers).  
- **Complexity:** Easy | **Blocks Prod:** No

### MED-07 — Meeting Status Transitions Allow Terminal Jumps, Reminder Claim Lacks `FOR UPDATE`, Silent Date/Time Defaults
- **Severity:** MEDIUM  
- **Category:** Business Logic / Concurrency / Validation  
- **File & Symbol:** `app/services/meeting_service.py` (`update_meeting_status` `lines 269-298`, `get_due_reminders` `lines 450-489`), `app/routers/tutor_calendar.py` (`parse_date_or_today`, `parse_time_or_default`, `lines 58-77`)  
- **Evidence:**  
  - `update_meeting_status` blocks only `!= SCHEDULED -> SCHEDULED`, allowing `CANCELLED -> COMPLETED`, `CANCELLED -> STUDENT_ABSENT`, or `COMPLETED -> CANCELLED` (note a `CANCELLED` meeting might overlap another active meeting, yet flipping it to `COMPLETED` bypasses overlap checks).  
  - `get_due_reminders` docstring states `"Ensures safe claiming across multiple worker processes without duplicate triggers"`, yet the query omits `.with_for_update()`.  
  - `tutor_calendar.py:58-77` swallows `ValueError`/`Exception` and silently substitutes today's date or `10:00` on invalid create/reschedule inputs.  
- **Recommended Fix:** Restrict `update_meeting_status` transitions to `SCHEDULED -> {COMPLETED, CANCELLED, STUDENT_ABSENT}` (plus explicit re-overlap check if any reverse transition were desired), add `.with_for_update(skip_locked=True)` in `get_due_reminders`, and return HTTP 400 validation errors on malformed date/time strings.  
- **Complexity:** Easy | **Blocks Prod:** No

### MED-08 — Unquoted Raw Exceptions & User Titles in `RedirectResponse` Query Parameters
- **Severity:** MEDIUM  
- **Category:** Backend Security / Input Handling  
- **File & Symbol:** `app/routers/tutor_practice_exams.py:277`, `app/routers/tutor_books.py:164,182,211,241,260`, `app/routers/tutor_videos.py:168,186,215,245,264`, `app/routers/tutor_tracks.py:160,179,198,216`  
- **Evidence:** `tutor_practice_exams.py:277` sets `url=f"/tutor/practice-exams/{exam_id}?msg=Reporting group '{title}' created"`; `tutor_books.py`, `tutor_videos.py`, and `tutor_tracks.py` catch `Exception as exc` and pass unquoted `{str(exc)}` directly into `?err={str(exc)}`.  
- **Explanation & Impact:** While Starlette percent-encodes non-ASCII characters (verified locally with Persian text), `&`, `#`, and `=` remain unescaped in `safe=":/%#?=@[]!$&'()*+,;"`, causing query truncation/parameter tampering; and bare `except Exception` leaks internal SQLAlchemy/Python error strings into URLs, browser history, Nginx logs, and HTML banners.  
- **Recommended Fix:** Replace bare `except Exception` with domain validation exceptions + generic internal error message, and always wrap URL query values in `urllib.parse.quote(..., safe="")`.  
- **Complexity:** Easy | **Blocks Prod:** No

### MED-09 — Frontend/Backend Upload Size Mismatch (`15 MB` Advertised vs `10 MB` Enforced)
- **Severity:** MEDIUM  
- **Category:** Frontend/Backend Consistency  
- **File & Symbol:** `app/core/storage.py:20`, `app/templates/student/exams/submit.html:49`, `app/templates/student/exams/edit.html:53`, `app/templates/tutor/historical_exams/create.html:64`  
- **Evidence:** `storage.py:20` enforces `REPORT_CARD_MAX_SIZE_BYTES = 10 * 1024 * 1024` (`10 MB`), while all three templates tell students/tutors `Max 15MB` (`en.json` and `fa.json`).  
- **Explanation & Impact:** Students scanning high-resolution report cards between 10–15 MB get an unexpected 400 error after upload despite following the stated limit.  
- **Recommended Fix:** Align template/locale copy to `10 MB` (or adjust `REPORT_CARD_MAX_SIZE_BYTES` to `15 * 1024 * 1024`—already well inside Nginx's `client_max_body_size 35M`).  
- **Complexity:** Very easy | **Blocks Prod:** No

### MED-10 — Four Broken Multiline Translations, EN/FA Label Swap & Inbox Poll Overwriting Search Filter
- **Severity:** MEDIUM  
- **Category:** Frontend UX / Localization  
- **File & Symbol:** `app/templates/student/practice_exams/list.html:11-12`, `app/templates/tutor/books/detail.html:12-13,77-78`, `app/templates/tutor/subjects/edit.html:42-43`, `app/templates/tutor/historical_exams/list.html:86`, `app/templates/tutor/messages/inbox.html:40`  
- **Evidence:**  
  1. Multiline `_("...\n   ...")` strings in those 4 template locations embed newlines and HTML indentation inside the translation key, missing exact keys in `fa.json` and rendering raw English (`Practice exams assigned...`, `Grade\n {g}`, `No chapters added...`, `Check one or more...`) in Persian RTL mode.  
  2. `tutor/historical_exams/list.html:86` renders `{{ _("Report Card") if is_rtl() else "کارنامه" }}` (showing Persian `"کارنامه"` in English mode).  
  3. `tutor/messages/inbox.html:37-40` polls `/tutor/messages/conversations` every 15s (`hx-get="/tutor/messages/conversations"`), overwriting `#conversations-container` without passing the active `#conversation-search` value `q`, wiping filtered search results mid-typing.  
- **Recommended Fix:** Normalize the 4 `_()` calls to single-line strings matching `en.json`/`fa.json`, fix the reversed ternary in `historical_exams/list.html:86`, and include `hx-include="#conversation-search"` on the 15s conversation poller (or pause polling while searching).  
- **Complexity:** Very easy | **Blocks Prod:** No

### MED-11 — Deployment Script Schema-Skew / Duplicate Migrations & Audit `RESTRICT` vs Cascade Mismatch
- **Severity:** MEDIUM  
- **Category:** Deployment / Database Migrations  
- **File & Symbol:** `scripts/manage.sh` (`cmd_update`, `lines 152-156`), `scripts/entrypoint.sh` (`lines 40-46`), `alembic/versions/2c3d4e5f6a7b_*.py`  
- **Evidence:** `manage.sh:153` runs `compose run --rm --no-deps web alembic upgrade head` **while the older `valhalla_web` container is still running**, then `compose up -d --no-deps web` triggers `entrypoint.sh` which runs `alembic upgrade head` a second time (and even before/during `manage.sh`, `entrypoint.sh` checks `AUTO_MIGRATE=true`). Meanwhile `2c3d4e5f6a7b` alters `completion_audit_logs.assignment_id` to `ondelete="RESTRICT"`, whereas `users -> study_plans -> plan_assignments` cascade delete.  
- **Explanation & Impact:** Running destructive/non-backward-compatible schema upgrades while an old `web` container still serves active users risks transient errors between lines 153 and 156 of `manage.sh`. Separately, while the app intentionally never deletes `User` rows (only deactivates), any future admin script deleting a student who completed tasks will fail with `IntegrityError` unless audit logs are handled explicitly.  
- **Recommended Fix:** Stop `web` (or run migrations cleanly in one place with `AUTO_MIGRATE=false` during scripted updates), test `alembic upgrade` + `downgrade` against PostgreSQL 16 in CI, and keep `User` deletion disallowed/explicitly archived.  
- **Complexity:** Moderate | **Blocks Prod:** No

### MED-12 — Specification / Documentation Drift on Student Assignment Undo (`STUDENT_UNDO`)
- **Severity:** MEDIUM  
- **Category:** Business Logic / Governance Consistency  
- **File & Symbol:** `docs/PRODUCT_SPEC.md:67,109`, `docs/AUTHORIZATION.md:86`, `docs/ARCHITECTURE.md:103` vs `app/routers/student.py:338-380`, `app/services/plan_service.py:843-881`, `app/templates/student/partials/{task_card,dashboard_task_item}.html`  
- **Evidence:** All three design docs explicitly state: *"Students can mark an assignment as completed with a single action. Students **cannot** directly undo or toggle off completion; only the tutor can reset completions."* Yet Stage 6 intentionally implemented student self-undo (`POST /student/assignments/{assignment_id}/undo` logging `CompletionAuditAction.STUDENT_UNDO`) with no time window, and tests in `test_grade_aware_completion_and_resources.py:175` and `test_business_logic_bypass.py:500` assert this behavior.  
- **Explanation & Impact:** If the tutor expects completion marks to lock after the daily deadline (or immediately), unbounded self-undo on active plans lets students toggle past-day tasks after missing deadlines. Conversely, if self-undo is wanted, the architecture/spec documents mislead operators.  
- **Recommended Fix:** Confirm intended product policy: either restrict `undo_assignment_completion` to before the task's deadline (or e.g. within X minutes) and document `STUDENT_UNDO`, or update `PRODUCT_SPEC.md` / `AUTHORIZATION.md` / `ARCHITECTURE.md` to reflect Stage-6 behavior accurately.  
- **Complexity:** Very easy | **Blocks Prod:** No

---

## 8. Low and Informational Findings

### LOW-01 — `format_chat_time` Double-Shifts Naive Local Clock in Non-UTC Container Environments
- **File & Symbol:** `app/core/templates.py:95`  
- **Evidence:** `now_local = to_local(datetime.now(), tz_name)` passes a naive local `datetime.now()` into `to_local()`, which attaches `timezone.utc` to naive datetimes (`app/core/timezone.py:29`). On UTC Docker containers this is benign; on hosts/dev machines with a non-UTC OS clock (e.g., `+03:30`), `"Today"` chat timestamps shift twice.  
- **Recommended Fix:** Replace `datetime.now()` with `now_utc()`.  
- **Complexity:** Very easy | **Blocks Prod:** No

### LOW-02 — Silent `video_count` Clamping & Archiving Draft Plans Directly
- **File & Symbol:** `app/services/plan_service.py:443-452, 565-566`  
- **Evidence:** `create_assignment` sets `if not calc_count or calc_count <= 0: calc_count = 1` when no video range is supplied instead of rejecting invalid non-positive counts; `archive_study_plan` transitions `DRAFT -> ARCHIVED` directly rather than requiring `PUBLISHED -> ARCHIVED` or deletion.  
- **Recommended Fix:** Validate `video_count > 0` explicitly (raising `PlanValidationError`) and clarify whether archiving drafts is desired.  
- **Complexity:** Very easy | **Blocks Prod:** No

### LOW-03 — Hardcoded `secure=True` Session Cookie, F-String `HTMLResponse` & Inconsistent HTMX Fallback CSRF Inputs
- **File & Symbol:** `app/routers/auth.py:83`, `app/routers/tutor_plans.py:316,368`, `app/templates/student/partials/{dashboard_task_item.html:64, task_card.html:68}`  
- **Evidence:** `auth.py:83` hardcodes `secure=True` on `valhalla_session`, blocking logins over plain `http://localhost` (e.g. non-Chrome strict browsers or HTTP health/staging) when `ENVIRONMENT=development`. `tutor_plans.py:316,368` constructs `HTMLResponse` via Python f-strings (`est.basis_text` is numeric-formatted today, not user-controlled, so not currently XSS, but fragile). The two student task completion `<form hx-post=...>` partials rely solely on `base.html`'s `X-CSRF-Token` JS hook and omit `<input type="hidden" name="csrf_token">` fallback.  
- **Recommended Fix:** Gate `secure=is_https or (settings.ENVIRONMENT.lower() == "production")`, escape/template `HTMLResponse` snippets in `tutor_plans.py`, and add hidden `csrf_token` inputs consistently.  
- **Complexity:** Very easy | **Blocks Prod:** No

### LOW-04 — Minor DB Invariant & Race Edges (`get_or_create_conversation`, Missing `CHECK` Constraints)
- **File & Symbol:** `app/services/message_service.py:59-71`, `app/models/exam.py`  
- **Evidence:** `get_or_create_conversation` performs check-then-insert against `uq_conversations_student_id` without catching `IntegrityError` if student and tutor open a new chat simultaneously. `Exam` date ordering (`first_exam_date <= last_exam_date`) and percentage bounds (`0 <= percentage <= 100`) are validated in services rather than DB `CHECK` constraints.  
- **Recommended Fix:** Handle `IntegrityError` with `SAVEPOINT` + re-select in `get_or_create_conversation`, and optionally add non-breaking DB `CHECK` constraints in a future migration.  
- **Complexity:** Easy | **Blocks Prod:** No

### LOW-05 — Test Suite Artifacts, Unisolated Demo Test & SQLAlchemy 2.0 `LegacyAPIWarning`
- **File & Symbol:** `tests/test_practice_exam.py:471-476`, `tests/test_demo_generator.py`, `tests/test_persian_redesign.py:125`, `app/services/exam_service.py:1398,1498,1702`  
- **Evidence:** `test_practice_exam_booklet_download_authorization` writes `dl_test_b1.pdf` and `dl_test_b2.pdf` directly to real `uploads/practice_booklets/` (both leftover files currently exist in the repo workspace!). `test_demo_generator.py` invokes `SessionLocal()` directly (mutating whatever DB `.env` points to). `test_persian_redesign.py:125` omits `re.DOTALL`, missing the 4 broken multiline `_()` keys (`MED-10`). `exam_service.py` triggers `LegacyAPIWarning` using `db.query(Model).get(...)` instead of `db.get(Model, ...)`.  
- **Recommended Fix:** Use `tmp_path` + `monkeypatch` in `test_practice_exam.py`, delete the 2 leftover test PDFs, gate or isolate `test_demo_generator.py`, add `re.DOTALL` in `test_persian_redesign.py`, and migrate `Query.get()` -> `Session.get()`.  
- **Complexity:** Easy | **Blocks Prod:** No

### INFO-01 — Architectural Coupling Affecting Future Multi-Tutor Support
- **File & Symbol:** `app/models/{subject.py, track.py, book.py, course.py, exam.py, practice_exam.py, message.py, settings.py}`, `app/services/message_service.py`  
- **Evidence:** `Subject.name` and `AcademicTrack.name` carry global `unique=True` indexes; `Subject`, `AcademicTrack`, `Book`, `Course`, `Exam`, `PracticeExam`, `HistoricalExamResult`, and `TelegramBackupSettings` have no `tutor_id` foreign key; `Conversation` enforces `UniqueConstraint("student_id")` globally; `user_service.list_students` and `exam_service.list_exams` return all rows globally rather than tenant-scoped by tutor; and router dependencies check `require_tutor` globally (`get_tutor_unread_count` includes `tutor_id IS NULL`).  
- **Recommendation for Future Multi-Tutor Phase:** Plan a future `tutor_id` scoping migration across curriculum/assessment/settings tables, drop global name uniqueness in favor of `(tutor_id, name)`, change `Conversation` uniqueness to `(student_id, tutor_id)`, and scope student directories to assigned tutors. Do not implement before initial single-tutor launch.  
- **Complexity:** Hard *(future roadmap)*

### INFO-02 — Service Monolith (`exam_service.py`) & Untracked Historical Helper Scripts
- **File & Symbol:** `app/services/exam_service.py` (3,186 lines), `scripts/` (26 historical i18n builder scripts + 10 demo scripts)  
- **Evidence:** `exam_service.py` combines exam definitions, recurring schedules, grade/track reporting configs, student submissions, tutor corrections, historical exams, bulk matrices, and comprehensive analytics in one file. `scripts/` retains 26 one-off catalog construction scripts (`add_batch_*.py`, `build_complete_fa_catalog*.py`).  
- **Recommended Fix:** Split `exam_service.py` into focused sub-modules (e.g., series/recurrence, submissions/corrections, analytics, historical exams) and archive one-off migration/i18n builder scripts.  
- **Complexity:** Moderate

### INFO-03 — No Automated Cron/Off-VPS `rsync` Provisioning & No Evidenced Live Restore Drill
- **File & Symbol:** `docs/BACKUP_AND_RESTORE.md`, `scripts/backup.sh`, `scripts/restore.sh`  
- **Evidence:** `backup.sh` and `restore.sh` are well-structured, including `--dry-run`, SHA-256 verification, and `pg_restore --list`, **but** VPS cron scheduling and off-VPS `rclone`/`rsync` replication remain manual setup steps, and no recorded restoration drill log/artifact exists in the repo. Telegram delivery partially serves off-site storage once `HIGH-02` encryption and `HIGH-03` locking are fixed.  
- **Complexity:** Easy

### INFO-04 — Unbounded Date Loop in Recurring Exam Date Generation
- **File & Symbol:** `app/services/exam_service.py:166-196` (`calculate_recurring_dates`)  
- **Evidence:** `while current <= last_exam_date:` validates `recurrence_interval_weeks >= 1` and `last_exam_date >= first_exam_date`, but does not cap maximum generated occurrences or date span. A mistyped year (e.g. `2999`) by the tutor loops ~50,000+ iterations.  
- **Recommended Fix:** Cap max span (e.g. `<= 2 years` or `<= 104 occurrences`) cleanly with `ExamValidationError`.  
- **Complexity:** Very easy

---

## 9. Security Assessment

- **Authentication (`app/routers/auth.py`, `app/services/auth_service.py`, `app/core/security.py`, `app/core/rate_limit.py`):**
  - *Strengths:* Uses `argon2-cffi` (`Argon2id`) for password hashing; stores only SHA-256 hashes of 256-bit `secrets.token_urlsafe(32)` tokens in `user_sessions`; enforces fixed 14-day non-rolling expiration (`calculate_session_expiry`); creates fresh tokens on login (preventing session fixation); revokes sessions on logout, deactivation, and password reset; sets `HttpOnly=True`, `SameSite=Lax`, `Secure=True`; no public registration endpoint exists (`test_no_public_student_registration`); `login_limiter` (SQLite-backed across workers) limits failed IP attempts to 5/60s with `TRUSTED_PROXIES` CIDR verification before trusting `X-Forwarded-For`.
  - *Weaknesses:* Case-sensitive username/email lookup mismatch vs lowercase storage (`MED-02`); timing oracle skipping Argon2 on missing/inactive accounts (`MED-02`); no minimum password length/complexity; IPv4-mapped IPv6 bug in `_clean_ip_str` (`MED-04`); Nginx `5r/m` rate limit catches legitimate shared-NAT `GET /auth/login` traffic (`MED-03`); `secure=True` breaks HTTP-only local dev (`LOW-03`).
- **Authorization (`app/core/dependencies.py`, all 20 routers):**
  - *Strengths:* Every tutor router enforces `Depends(require_tutor)` and `Depends(verify_csrf_token)` at router or route level; every student router enforces `Depends(require_student)` and `Depends(verify_csrf_token)`. Student queries consistently scope to `current_user.id` (`PlanAssignment.student_id`, `StudentPracticeAttempt.student_id`, `Conversation.student_id`, `StudentExamResult.student_id`, `HistoricalExamResult.student_id`). Cross-student exam/booklet/plan/chat/history IDORs were checked across all 20 routers and found properly guarded—returning 403/404 cleanly.
  - *Weaknesses:* In `tutor_scheduler.py:310-321`, `item.proposal_id != proposal_id` is checked *after* `update_proposal_item` commits (`MED-06`, tutor-only endpoint, zero cross-student impact). Also `study_plan` service defaults `tutor_id: Optional[uuid.UUID] = None`, which works safely for 1 tutor but will need strict enforcement for multi-tutor (`INFO-01`).
- **Web Security (XSS, CSRF, Redirects, Headers, CSP):**
  - *Strengths:* Zero `| safe` filters and zero `.innerHTML` assignments exist across all 81 `.html` templates (confirmed by programmatic scan and regression tests). JSON payloads pass safely via `<script type="application/json">{{ ... | tojson }}</script>`. `is_safe_redirect_url` (`tutor.py:317`) and `i18n.js` preserve open-redirect safety. Security headers (`X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy`, `frame-ancestors 'self'`, `object-src 'none'`, conditional `HSTS`) are injected on every response in `app/main.py:98-130`. `verify_csrf_token` uses `secrets.compare_digest` on `X-CSRF-Token` header or form `csrf_token`. Meeting URL validation permits only `http`/`https`.
  - *Weaknesses:* External CDNs without SRI + `'unsafe-inline' 'unsafe-eval'` CSP (`HIGH-07`); unquoted `Location` params / raw `str(exc)` leakage (`MED-08`); unescaped Python f-string `HTMLResponse` in `tutor_plans.py:316,368` (`LOW-03`); two HTMX forms omit hidden `csrf_token` (`LOW-03`).
- **Backend Security (SQLi, Uploads, Downloads, DoS, Logging):**
  - *Strengths:* All queries use SQLAlchemy parameterized ORM/Core expressions (`text()` uses bound parameters `:lock_id`); `ilike` uses bound `f"%{q}%"`. `storage.py` validates extension allowlists, MIME allowlists, magic bytes on first 64 KB chunk, incremental byte caps (25 MB booklets / 10 MB report cards), UUID filenames on disk, and canonical `Path.resolve().is_relative_to(base)` rejecting `..`, null bytes, and absolute paths. `/health/db` sanitizes DB errors in JSON and logs internal details server-side. `telegram_backup_service.sanitize_telegram_error` redacts bot tokens and DB URLs.
  - *Weaknesses:* `pg_dump` subprocess runs unencrypted in `create_and_deliver_manual_backup` (`HIGH-02`); `calculate_recurring_dates` lacks max-count cap (`INFO-04`); exception query strings leak `str(exc)` in older CRUD routers (`MED-08`); `tutor_practice_exams.py:277` fails to `quote()` title.
- **Configuration & Secrets:**
  - *Weaknesses:* Default `SECRET_KEY` is not rejected in production (`HIGH-06`); workspace `.env` uses development defaults (excluded from Docker build by `.dockerignore`, but risk if copied blindly to VPS).

---

## 10. Business Logic Assessment

- **Study Plans (`plan_service.py`, `tutor_plans.py`, `student.py`):**
  - 14-day boundaries (`start_date + 13 days`), grade/subject hierarchy checks (`course_chapter -> course -> subject -> student_effective_subjects`), completion timestamps, audit trails (`COMPLETED`, `RESET`, `STUDENT_UNDO`), and `ARCHIVED` read-only protections are strongly implemented with row locks (`_lock_study_plan_row`, `_lock_assignment_with_plan`).
  - *Gaps:* Reversed lock order `StudyPlan -> User -> StudyPlan` in `publish_study_plan` (`MED-01`); spec conflict on student self-undo (`MED-12`); `video_count <= 0` silent clamp to `1` and direct `DRAFT -> ARCHIVED` archival (`LOW-02`).
- **External & Historical Exams (`exam_service.py`, `tutor_exams.py`, `student_exams.py`, `tutor_historical_exams.py`, `student_historical_exams.py`):**
  - Strong eligibility rules (grade + track + direct assignment fallback), strict/late deadline tracking (`is_late`), reporting-group snapshot preservation, tutor score corrections with `ExamAuditLog`, `CANCELLED` finality, and historical exam isolation.
  - *Gaps:* `NameError: Subject` 500 crash (`HIGH-01`); dropped `subject_results` across comparison/series/comprehensive analytics and broken `"دهم"`/`"یازدهم"`/`"دوازدهم"` grade filter (`HIGH-04`); `ExamAuditLog` cascade deletion + missing delete row locks (`HIGH-05`); unbounded `calculate_recurring_dates` (`INFO-04`).
- **Practice Exams (`practice_exam_service.py`, `tutor_practice_exams.py`, `student_practice_exams.py`, `runner.html`):**
  - Sequential multi-booklet progression, server-authoritative `expires_at` timer lock, automatic expiration handling, booklet download locking after advancement, atomic scoring with negative marking support, and safe DOM auto-save UI (`runner.html`) are well designed.
  - *Gaps:* Starting an exam with 0 configured questions is allowed (`MED-05`); no edit/deactivate/delete routes for practice exams, booklets, or reporting groups (`MED-05`); no DB partial unique index for active `IN_PROGRESS` attempts (`MED-05`).
- **Meetings & Semi-Automatic Scheduler (`meeting_service.py`, `scheduler_service.py`, `tutor_calendar.py`, `tutor_scheduler.py`):**
  - Strong tutor-level time overlap prevention with row locking (`User` lock on meeting creation/reschedule), `MeetingRescheduleHistory`, terminal state reschedule blocks, recency-weighted preference learning (`>=2` completed sessions), day-by-day availability windows (`custom`/`open`/`none`), and safe draft/approved proposal workflow.
  - *Gaps:* `update_meeting_status` permits invalid terminal state jumps (`CANCELLED <-> COMPLETED` / `STUDENT_ABSENT`) without overlap check (`MED-07`); `get_due_reminders` lacks `.with_for_update()` (`MED-07`); silent today/`10:00` date/time fallbacks (`MED-07`); `post_update_proposal_item` commits before checking `proposal_id` ownership (`MED-06`); stale conflicts kept when regeneration finds no slot + English-only notices + non-atomic `quick_move_meeting` notification commit (`MED-06`).
- **Messaging (`message_service.py`, `student_chat.py`, `tutor_messages.py`):**
  - Clean 1:1 student-tutor `Conversation` model, ownership checks on poll/older/send, automatic read receipt updates when recipient fetches/polls messages, rate limiting (30/60s), empty & >5,000-char rejection, proper URL encoding (`%2B`) for timezone-aware `+` timestamps. Message deletion is not implemented (intentional).
  - *Gaps:* `list_tutor_conversations` N+1 (`HIGH-08`); 15s polling drops search query (`MED-10`); `get_or_create_conversation` lacks `IntegrityError` race handling (`LOW-04`).

---

## 11. Database Assessment

- **Schema & Constraints (`app/models/`, 21 `alembic/versions/*.py`):**
  - Consistent UUID primary keys, timezone-aware `DateTime(timezone=True)` columns, and explicit `POSTGRES_NAMING_CONVENTION` (`ix`, `uq`, `ck`, `fk`, `pk`) across `Base`.
  - Strong database-enforced invariants where most needed:
    - Partial unique index `uq_study_plans_student_published` (`WHERE status = 'PUBLISHED'`).
    - Composite `(id, student_id)` FK between `study_plans` and `plan_assignments` preventing cross-student task injection even at SQL level.
    - `ondelete="RESTRICT"` on `completion_audit_logs.assignment_id` (`2c3d4e5f6a7b`) and curriculum FKs (`track_subjects.subject_id`, `courses.subject_id`, `books.subject_id`) preventing silent history loss.
    - Composite/unique constraints on `student_exam_results (exam_session_id, student_id)`, `exam_series_assignments (exam_id, student_id)`, `exam_grade_track_configs (exam_id, grade, track_id)`, `conversations.student_id`, and `student_practice_answers (booklet_attempt_id, question_number)`.
  - *Database Gaps:*
    - `exam_audit_logs.exam_id` uses `ondelete="CASCADE"`, destroying deletion audits (`HIGH-05`).
    - Missing PostgreSQL partial unique index on `student_practice_attempts (student_id, practice_exam_id) WHERE status = 'IN_PROGRESS'` (`MED-05`).
    - Missing DB `CHECK` constraints on percentages (`0..100`) and non-negative correct/incorrect counts (`LOW-04`).
    - `completion_audit_logs` `RESTRICT` blocks direct `User` deletion cascade (`MED-11`).
    - Minor constraint naming quirk (`ck_course_chapters_ck_course_chapters_...`) in `7b3e21a8d055`, benign functionally.
- **Migration Safety & Pooling:**
  - All 21 migrations form a single linear chain from `9c005c0812c7` to `4e5f6a7b8c9d` with working `batch_alter_table` support; mostly additive upgrades with no destructive column drops.
  - `pool_size=10`, `max_overflow=10`, `pool_pre_ping=True`, `pool_timeout=15`, `pool_recycle=1800` across `WEB_CONCURRENCY=2` (max 40 DB connections) pairs safely with PostgreSQL `max_connections=150`.
  - `test_database.py` passes SQLite schema upgrade, but neither `alembic downgrade` nor PostgreSQL `alembic upgrade head` is exercised in tests (`scripts/manage.sh:153` schema-skew window noted in `MED-11`).

---

## 12. Performance Assessment

*Methodological note: No live load tests were executed against PostgreSQL/Docker in this read-only audit. All figures below are code-based engineering estimates grounded in `docker-compose.yml`, `app/core/database.py`, `nginx/valhalla.conf`, and inspected queries.*

- **Hardware Adequacy (2 CPU cores, 4 GB RAM, 1 tutor + up to 100 students):**
  - Container budgets in `docker-compose.yml` total `1 GB` (`web`) + `768 MB` (`db`) = `1.75 GB` limits (`~512 MB` reservations), leaving >2 GB headroom on a 4 GB VPS for Nginx, OS cache, and `pg_dump` runs.
  - All FastAPI route handlers are synchronous (`def`, verified by `test_critical_blockers_regressions.py:52`) running in AnyIO's worker threadpool (40 threads/worker × 2 workers) without event-loop blocking on DB calls.
- **Workload Estimates by Concurrency Tier:**
  - **10 simultaneous active students:** Very smooth (<50–150 ms typical SSR routes); background polling (`15s` unread counts = ~1.3 req/s; `4s` active chat poll = ~2.5 req/s) is trivial.
  - **25 simultaneous active students:** Comfortable once `HIGH-07` external CDN load and `MED-03` Nginx login rate-limit are fixed. Argon2id login verification is CPU-intensive (~50–150 ms/login); 25 logins spread over 30–60s stay well within 2 cores.
  - **50 simultaneous active students (e.g., end of a timed practice exam or checking mock exam results):** **Bottlenecks emerge** if `HIGH-08` is unfixed:
    - `/student/exams` and `/student/practice-exams` load all students' results/attempts (`O(students × exams)` rows) + N+1 per-exam config queries.
    - 50 simultaneous Argon2 logins within 2 seconds queue briefly behind 2 vCPUs (~1.5–3s tail latency).
    - Background `every 15s` unread badge polling runs **twice** per page (`desktop` + hidden `mobile` badge = ~6.7 req/s across 50 open tabs).
  - **Tutor working while students are active:** `GET /tutor/exams` runs N+1 incompatibility queries (`exam_service.py:2582`), and `/tutor/messages` runs `2N+1` (~201 queries for 100 students) on initial load and every 15s poll (`HIGH-08`). If scheduled Telegram backup triggers `pg_dump` + `gzip` + multi-part HTTP upload inside a web worker (`main.py:50`), that worker incurs brief CPU/memory pressure while the second worker continues serving HTTP.
- **Do we need Redis, Celery, microservices, or Kubernetes?** **No.** Plain PostgreSQL + Uvicorn (`2` workers) + Nginx cleanly handles 100 students on a single 2-core / 4 GB VPS once the few O(N) queries and external CDNs are cleaned up.

---

## 13. Frontend Assessment

- **Strengths:** Clean Tailwind responsive design (44px touch targets on mobile actions), comprehensive Persian (`fa` RTL) + English (`en` LTR) localization (`2,260` perfectly aligned translation keys in `en.json` and `fa.json`, `persian-ui.css` RTL rules, Jalali dates, Persian digits/durations), Saturday-first Persian calendar ordering, and `runner.html` DOM updates strictly via `createElement` + `textContent` + `replaceChildren`.
- **Reliability & UX Weaknesses Found:**
  1. **External CDN dependency (`HIGH-07`):** Tailwind Play CDN + `unpkg.com` HTMX + unpinned `chart.js` CDN break the entire UI/HTMX/charts if blocked/throttled in Iran.
  2. **4 broken multiline `_()` keys (`MED-10`):** Render raw English paragraphs/`Grade\n {g}` inside Persian UI (`practice_exams/list.html`, `tutor/books/detail.html`, `tutor/subjects/edit.html`).
  3. **EN/FA inversion (`MED-10`):** `tutor/historical_exams/list.html:86` shows Persian `"کارنامه"` when `get_locale() == "en"`.
  4. **Grade filter mismatch (`HIGH-04`):** `tutor/exams/compare_students.html:22-24` submits `"دهم"`/`"یازدهم"`/`"دوازدهم"` while students use `"10"`/`"11"`/`"12"`.
  5. **Upload size mismatch (`MED-09`):** `student/exams/{submit,edit}.html` and `tutor/historical_exams/create.html` display `Max 15MB` while backend rejects `>10 MB`.
  6. **Inbox search lost on poll (`MED-10`):** `tutor/messages/inbox.html:40` polls `/tutor/messages/conversations` every 15s without preserving search term `q`.
  7. **Silent calendar fallbacks & missing CSRF hidden inputs (`MED-07`, `LOW-03`):** `dashboard_task_item.html:64` and `task_card.html:68` omit hidden `csrf_token` (work via HTMX `X-CSRF-Token` header); duplicate unread pollers collide/double traffic in `base.html` and `mobile_nav_drawer.html`.

---

## 14. Infrastructure and Deployment Assessment

- **Docker & Compose (`Dockerfile`, `docker-compose.yml`, `docker-compose.dev.yml`, `scripts/entrypoint.sh`):**
  - *Positives:* Python 3.12-slim + `postgresql-client-16` installed (`pg_dump` version-matched to `postgres:16-alpine`), dedicated non-root `appuser:10001`, `no-new-privileges:true`, `127.0.0.1:${PORT:-8000}:8000` loopback-only binding, `postgres` not published on host in production compose, JSON log rotation (`10m` × `3` files), `stop_grace_period: 30s`, `depends_on: db: service_healthy`, `db_wait_retries` + `AUTO_MIGRATE` in `entrypoint.sh`, sensible memory limits (`768M` db + `1G` web).
  - *Gaps:* Default `SECRET_KEY` not blocked at startup in production (`HIGH-06`); `scripts/manage.sh update` runs `alembic upgrade head` while old `web` still serves traffic + re-runs it in `entrypoint.sh` (`MED-11`); `--forwarded-allow-ips=*` in `Dockerfile:41` means if `valhalla_web` were ever exposed beyond Nginx/host loopback, client `X-Forwarded-Proto` spoofing could trick `add_security_headers` into emitting HSTS over HTTP (safe only because `127.0.0.1:8000` is loopback-bound + Nginx sets `X-Forwarded-Proto`).
- **Nginx (`nginx/valhalla.conf`):**
  - *Positives:* HTTP->HTTPS redirect, modern TLSv1.2/1.3 ciphers, `client_max_body_size 35M`, gzip enabled, HTTP/1.1 keepalive upstream to `127.0.0.1:8000`.
  - *Gaps:* Login `5r/m` rate limit catches `GET` + shared-NAT users (`MED-03`); proxy timeouts missing on login and messaging location blocks (`MED-03`); placeholder domain/Certbot chicken-and-egg (`MED-03`).

---

## 15. Backup and Recovery Assessment

Evaluating recovery across failure scenarios:

| Scenario | Current Capability & Verdict |
|---|---|
| **Accidental student deletion** | **Strong at app level** (no delete endpoint exists; tutors can only deactivate accounts). However, direct DB `DELETE` on `users` is blocked by `completion_audit_logs` `ondelete="RESTRICT"` (`MED-11`). |
| **Database corruption** | **Fair locally, Flawed off-site:** `scripts/backup.sh` uses atomic temp staging, `pg_dump -F c`, `pg_restore --list`, `SHA256SUMS`, retention (`14d` / min `7`), and `restore.sh` restores cleanly via `--single-transaction`. Off-site Telegram backup has unencrypted payload (`HIGH-02`) and advisory lock wedge risk (`HIGH-03`). |
| **Failed migration** | Pre-update backup exists in `manage.sh update` (`backup.sh --no-telegram`), though double-migration / live-container migration window exists (`MED-11`), and `alembic downgrade` paths are untested. |
| **VPS failure** | Only recoverable if cron + off-VPS sync (`rsync`/`rclone`) OR Telegram backup is configured and working (`INFO-03`, `HIGH-02`, `HIGH-03`). Local `./backups` dies with the VPS disk. |
| **Disk exhaustion** | Docker JSON logs are rotated (`30 MB` max/service), and `backup.sh` prunes old archives—**but** uploaded booklets (`25 MB`) and report cards (`10 MB`) in `uploads_data` have no total quota/cleanup on delete, and PostgreSQL WAL/backups share host disk. |
| **Failed deployment / Container failure** | `restart: unless-stopped` + `/health/db` healthcheck + `manage.sh` handle restarts cleanly; previous Docker image isn't automatically rolled back by `manage.sh`. |
| **Lost uploaded files** | Covered in both `backup.sh` (`uploads.tar.gz`) and `telegram_backup_service.py` (`uploads.tar.gz`), and restored atomically by `restore.sh`. |
| **Actual restoration test evidence** | **`restore.sh --dry-run` is documented (`docs/BACKUP_AND_RESTORE.md`), yet zero automated restore verification tests or recorded drill logs exist in the repository.** |

---

## 16. Test Coverage Assessment & Execution Results

- **Suite Inventory:** **277 tests collected** across 44 test files (`pytest --collect-only -q`).
- **Actual Test Run Performed (Read-Only):**
  - Unified non-`TestClient` suite across 153 test definitions in 30 files/subsets (`test_academic_service`, `test_additional_requirements_workflow`, `test_audit_fixes_batch2`, `test_audit_fixes_batch3`, `test_auth_service`, `test_cli`, `test_config`, `test_critical_blockers_regressions`, `test_database`, `test_exam_service`, `test_external_and_historical_exams`, `test_external_exam_audit_fixes`, `test_external_exam_series_workflow`, `test_meeting_service`, `test_plan_service`, `test_rate_limit`, `test_resource_service`, `test_scheduler_service`, `test_security`, `test_stage3_curriculum`, `test_storage`, `test_telegram_backup`, `test_timezone`, `test_user_service`, plus all non-`TestClient` test functions in `test_business_logic_bypass`, `test_grade_aware_completion_and_resources`, `test_persian_redesign`, `test_practice_exam`, `test_security_audit_regressions`, and `test_stage4_planner`): **`174 passed, 0 failed` (`27 warnings` in `31.16s`)** with zero code/test modifications.
- **Tests NOT Executed (Exact Scope & Environment Causes):**
  1. **97 `TestClient`-based tests** (12 pure `TestClient` files: `test_auth_routes.py`, `test_authorization.py`, `test_csrf.py`, `test_curriculum_routes.py`, `test_exam_routes.py`, `test_health.py`, `test_meeting_calendar_routes.py`, `test_messaging.py`, `test_scheduler_routes.py`, `test_stage5_student_experience.py`, `test_telegram_backup_routes.py`, `test_tutor_student_management.py`; plus 30 `TestClient` cases across 6 mixed files: `test_business_logic_bypass.py`, `test_grade_aware_completion_and_resources.py`, `test_persian_redesign.py`, `test_practice_exam.py::test_practice_exam_booklet_download_authorization`, `test_security_audit_regressions.py`, `test_stage4_planner.py`): **blocked in the Windows sandbox**. Diagnosed via `python -X faulthandler`: `starlette.testclient.TestClient` starts an AnyIO `BlockingPortal` using `asyncio.ProactorEventLoop._make_self_pipe()`, which falls back to `socket._fallback_socketpair()` (`127.0.0.1` loopback connect/accept) and hangs because sandbox policy blocks local port binding/loopback.
  2. **5 PostgreSQL integration tests** (`tests/test_postgres_integration.py`): intentionally skipped (`@pytest.mark.skipif(not is_postgres_available())`, and not run against host DB to preserve strict read-only guarantees).
  3. **1 demo lifecycle test** (`tests/test_demo_generator.py`): **intentionally excluded** because it bypasses `conftest.py`'s SQLite fixture, connects directly to `SessionLocal()` (live `.env` DB), and executes destructive `cleanup_demo_data()` + inserts demo records and PDFs.
- **Test Quality & Blind Spots Identified:**
  - *Heavy mocks / SQLite divergence:* `test_telegram_backup.py` mocks `httpx.MockTransport`, `subprocess.run`, and `shutil.which` (never verifying real archive encryption/restoration or PostgreSQL advisory unlock error recovery). Core unit tests run on SQLite in-memory without `PRAGMA foreign_keys=ON` globally in `conftest.py` (though `test_business_logic_bypass.py` & `test_postgres_integration.py` explicitly verify DB `RESTRICT` and row locks).
  - *Critical missing tests:* Blank group name submission in `post_configure_grade_track` (`HIGH-01`), `safe_delete_exam_series` audit log preservation (`HIGH-05`), `compare_students_on_session` with `"10"`/`"11"`/`"12"` grades and subject-only results (`HIGH-04`), Alembic `downgrade` + PostgreSQL migration up/down verification (`MED-11`), and `re.DOTALL` in `test_persian_redesign.py:125` (`LOW-05`).
  - *Workspace pollution:* `test_practice_exam_booklet_download_authorization` writes `dl_test_b1.pdf` and `dl_test_b2.pdf` directly into workspace `uploads/` (`LOW-05`).

---

## 17. Previous Audit Findings Verification

*(Historical standalone audit/progress docs were removed in commit `998fb2d`; verification below cross-checks prior remediation commitments documented in `docs/`, `tests/test_*audit*.py`, `test_business_logic_bypass.py`, `test_security_audit_regressions.py`, and `test_critical_blockers_regressions.py` against current code.)*

| Prior Audit Area / Finding | Classification | Current Verification Notes |
|---|---|---|
| Practice exam booklet addition locked after attempt start (`#1`) | **Fixed and verified** | Guarded with row locks in `practice_exam_service.py` + `test_postgres_integration.py`. |
| Cancelled exam occurrences reopened by restore/bulk-restore (`#2`) | **Fixed and verified** | Enforced in `exam_service.py` + `test_business_logic_bypass.py`. |
| Student result edit racing tutor review lock (`#3`) | **Fixed and verified** | Verified with `with_for_update()` + `populate_existing()` + PG concurrency test. |
| Exam & practice exam unchecked-student revocation (`#4`, sibling `#5`) | **Fixed and verified** | Revokes unsubmitted omitted assignments while preserving historical results. |
| Archived exam series mutations & student subject fail-closed (`#5`, `#6`) | **Fixed and verified** | Archived series reject edits/configs/sessions/assignments; empty subjects fail closed. |
| Stale ORM completion/delete/reset/archive plan races (`#7`–`#12`) | **Fixed and verified** | Hierarchical row locks + `refresh` + `RESTRICT` FK on `completion_audit_logs`. |
| Terminal meetings reactivated via reschedule/quick-move (`#13`) | **Partially fixed** | Blocked on reschedule, quick-move, and `-> SCHEDULED`; **still open** on `CANCELLED <-> COMPLETED` / `STUDENT_ABSENT` status transitions (`MED-07`). |
| Exam series & session safe deletion + audit logging | **Still present / Regression** | `safe_delete_exam_series` cascades away its own `DELETED` audit row (`HIGH-05`), lacks row locks, and `post_configure_grade_track` has `NameError: Subject` (`HIGH-01`). |
| Scheduler discarded proposal & bad reminder validation (`batch3`) | **Partially fixed** | Discarded checks & invalid `HH:MM`/`reminder_minutes` fixed; `post_update_proposal_item` still commits before verifying `proposal_id` (`MED-06`) and calendar date helpers still silently default invalid inputs (`MED-07`). |
| Practice exam auto-submit disabling choice radios & timer bypass | **Fixed and verified** *(code & unit)* | `runner.html` uses `pointer-events-none` + `isSubmitting`; server enforces `expires_at` (`TestClient` E2E blocked in sandbox). |
| DOM XSS in `runner.html` & unsafe `| safe` JSON serialization | **Fixed and verified** | Zero `innerHTML` and zero `| safe` in all 81 templates; `tojson` `<script type="application/json">` used; `i18n.py` blocks placeholder injection. Minor raw f-string `HTMLResponse` remains in `tutor_plans.py:316,368` (`LOW-03`). |
| Tutor provisioning (`cli.py` + no public registration) | **Fixed and verified** | Tested in `test_cli.py` and `test_tutor_student_management.py`. |
| Database migration chain & SQLite upgrade | **Fixed but insufficiently tested** | Linear 21-revision chain passes SQLite `upgrade head`; PostgreSQL `upgrade`/`downgrade` untested in CI, and `manage.sh` runs migrations against live `web` (`MED-11`). |
| Backup & restoration (`pg_dump` `PGPASSWORD`, error redaction, `backup.sh`/`restore.sh`) | **Partially fixed / Still present** | Shell scripts and password redaction work well; web/scheduled Telegram backups still send **unencrypted** archives (`HIGH-02`), advisory unlock can leak on error (`HIGH-03`), and no live restore test exists (`INFO-03`). |
| Nginx & Docker port consistency (`127.0.0.1:8000`) | **Fixed and verified** | Compose & Nginx ports align cleanly; classroom NAT rate-limit on `GET /auth/login` and location timeout omissions remain (`MED-03`). |

---

## 18. Future Architectural Concerns (Multi-Tutor Readiness)

Single-tutor design is intentional and appropriate for launch. When expanding to multiple tutors later, these specific structural points will require deliberate migration work (`INFO-01`):
1. Add `tutor_id` FK ownership to `subjects`, `academic_tracks`, `books`, `courses`, `exams`, `practice_exams`, `historical_exam_results`, and per-tutor `telegram_backup_settings` (or system-admin-only backups).
2. Convert global `unique=True` on `subjects.name` and `academic_tracks.name` to composite `(tutor_id, name)` uniqueness.
3. Convert `conversations.student_id` uniqueness to `(student_id, tutor_id)` and drop the `Conversation.tutor_id.is_(None)` fallback in `message_service.py`.
4. Introduce a tutor-student enrollment link (or `student.tutor_id`) and enforce it inside `user_service.list_students`, `exam_service.list_exams`, `plan_service` defaults (`tutor_id: Optional` -> required), and route handlers instead of relying on `require_tutor` alone.

---

## 19. Recommended Production Configuration

Before launch on Ubuntu 22.04/24.04 (2 vCPU, 4 GB RAM):
1. **`.env` (never commit):**
   - `ENVIRONMENT=production`, `DEBUG=False`, `DEFAULT_TIMEZONE=Asia/Tehran`
   - `SECRET_KEY`: fresh 64-hex random string (`openssl rand -hex 32`) validated non-default at startup (`HIGH-06`)
   - `POSTGRES_SERVER=db`, `POSTGRES_PORT=5432`, strong `POSTGRES_PASSWORD` (`openssl rand -base64 24`)
   - `AUTO_MIGRATE=true` (with `manage.sh` stopping old `web` before running migrations or relying on single execution during rollout)
   - `WEB_CONCURRENCY=2` (optimal for 2 vCPUs with `pool_size=10, max_overflow=10` per worker = max 40 PostgreSQL connections out of `max_connections=150`)
   - `BACKUP_PASSPHRASE_FILE=/root/.valhalla_backup_key` (or `BACKUP_ENCRYPTION_KEY`) mandatory for all encrypted off-site/Telegram backups.
2. **Frontend Static Assets & CSP:**
   - Precompiled local Tailwind CSS (`app/static/css/tailwind.css`) + local vendored `htmx.min.js` and `chart.umd.min.js` (zero external CDN calls, strict `'self'` CSP without `'unsafe-eval'`).
3. **Nginx Reverse Proxy:**
   - Bootstrap HTTP Certbot -> enable HTTPS block in `nginx/valhalla.conf` with real domain, apply `limit_req` to `POST /auth/login` only (or higher burst `>=30` for shared NAT classrooms), and include timeouts (`120s`) in all proxy locations.
4. **Backup Schedule:**
   - Host cron running `scripts/backup.sh --passphrase-file /root/.valhalla_backup_key` daily (`03:15` Tehran time) + encrypted Telegram delivery (once `HIGH-02` & `HIGH-03` are fixed) + monthly `restore.sh --dry-run` and quarterly test-VPS restore verification.

---

## 20. Prioritized Remediation Plan

### Phase 1 — Mandatory Launch Blockers (Before Production Deployment)
1. **Fix `NameError: Subject` in `app/routers/tutor_exams.py`** (`HIGH-01`, Easy).
2. **Fix external exam subject-only analytics & compare grade filter (`"10"`/`"11"`/`"12"`)** (`HIGH-04`, Easy).
3. **Preserve `ExamAuditLog` across deletions (`ondelete="SET NULL"`) & add row locks on delete** (`HIGH-05`, Moderate).
4. **Encrypt Telegram backup archives before upload & update misleading UI/docs** (`HIGH-02`, Moderate).
5. **Fix PostgreSQL advisory lock rollback/unlock + move `next_run_at` check inside lock** (`HIGH-03`, Easy).
6. **Fail closed at startup if `ENVIRONMENT=production` uses default/short `SECRET_KEY` or default DB password** (`HIGH-06`, Very easy).
7. **Bundle Tailwind CSS, HTMX & Chart.js locally in `app/static/` and remove CDN / `'unsafe-eval'` from CSP** (`HIGH-07`, Moderate).
8. **Run full `./scripts/run_docker_tests.sh` on Ubuntu Docker + PostgreSQL 16 (verifying all 277 tests including `TestClient` and `test_postgres_integration.py`)** + remove leftover `uploads/practice_booklets/dl_test_b*.pdf`.

### Phase 2 — High-Priority Pre-Peak & Operational Fixes (Recommended Before Full 100-Student Rollout)
9. **Optimize N+1 & cross-student eager-loading queries (`exam_service`, `practice_exam_service`, `message_service`, duplicate unread pollers)** (`HIGH-08`, Moderate).
10. **Fix Nginx shared-NAT login GET rate limit & unify timeouts** (`MED-03`, Easy).
11. **Fix `MED-01` (`publish_study_plan` lock order), `MED-02` (case-insensitive login + timing equalization + password length), `MED-04` (IPv4-mapped IPv6 rate-limit key + WAL init), `MED-06` (scheduler `proposal_id` check before commit, stale conflicts, localized notices), `MED-07` (meeting state transitions, reminder `FOR UPDATE`, 400 on bad dates), `MED-08` (quote redirect URLs & hide raw `str(exc)`), `MED-09` (`10 MB` vs `15 MB` text), `MED-10` (4 multiline `_()` keys, EN/FA swap, inbox search preserve), `MED-12` (resolve undo policy vs docs).**

### Phase 3 — Post-Launch Hardening & Maintainability
12. **Add practice exam 0-question start guard, edit/deactivate/delete routes, and `IN_PROGRESS` DB unique index** (`MED-05`, Moderate).
13. **Harden `manage.sh` zero-skew update window & add PostgreSQL upgrade/downgrade test** (`MED-11`, Moderate).
14. **Fix `LOW-01`..`LOW-05` (`format_chat_time` UTC, `video_count` validation, dev cookie `secure` flag, `get_or_create_conversation` race, test suite isolation & `Session.get()`), `INFO-04` (`calculate_recurring_dates` cap), and `INFO-02`/`INFO-03` (monthly restore drill + refactor `exam_service.py`).**

---

## 21. Final Recommendation — Direct Answers (Section 16)

1. **Would you trust this exact codebase with 100 real students?**  
   **Not as-is today.** While the core security/isolation model is strong, the exam configuration HTTP 500 bug (`HIGH-01`), broken subject-only analytics/grade comparison (`HIGH-04`), unencrypted Telegram backup leakage (`HIGH-02`), scheduled backup advisory-lock wedge hazard (`HIGH-03`), audit log deletion on exam delete (`HIGH-05`), unguarded `SECRET_KEY` (`HIGH-06`), and external CDN dependency for Iranian users (`HIGH-07`) create unacceptable launch risk. After fixing Phase 1 (+ Nginx NAT tuning and `HIGH-08` query fixes), yes—it will be trustworthy for 1 tutor and 100 students.

2. **Would you deploy it on a 2-core / 4 GB VPS?**  
   **Yes, once Phase 1 & `HIGH-08` query fixes are applied.** With `WEB_CONCURRENCY=2`, `pool_size=10`/`max_overflow=10`, PostgreSQL `shared_buffers=256MB`, and prebuilt local static assets, 2 vCPU / 4 GB RAM has comfortable margin (~1.75 GB compose limits) for 100 students and typical bursts of 10–50 concurrent users.

3. **What are the five most dangerous problems?**  
   1. Unencrypted database + student upload backups transmitted to Telegram despite UI claiming encryption (`HIGH-02`).  
   2. Scheduled Telegram backup advisory lock wedge silently halting all future automated off-site backups (`HIGH-03`).  
   3. External unpinned CDNs without SRI + `'unsafe-eval'` CSP threatening total UI outage in Iran (`HIGH-07`).  
   4. `NameError: Subject` crash in exam configuration (`HIGH-01`) + silent drop of subject-based exam analytics & grade filter (`HIGH-04`).  
   5. Destruction of exam series `DELETED` audit logs via `CASCADE` (`HIGH-05`) + missing startup validation rejecting default `SECRET_KEY` in production (`HIGH-06`).

4. **Which problems are easy to fix?**  
   `HIGH-06` (`SECRET_KEY` check), `HIGH-01` (`Subject` import), `HIGH-03` (`rollback()` + lock placement), `HIGH-04` (subject fallback + grade alias in compare), `MED-01` (lock order), `MED-02` (lowercase login/password check), `MED-03` (Nginx `limit_except`/burst), `MED-04` (IPv4-mapped IPv6 parser), `MED-06`..`MED-10`, `MED-12`, `LOW-01`..`LOW-05`, `INFO-03`, and `INFO-04` (**21 of 29 total findings** are Very Easy or Easy).

5. **Which require moderate work?**  
   `HIGH-02` (encrypted Telegram bundles + restore integration), `HIGH-05` (`ExamAuditLog` `SET NULL` migration + deletion locks), `HIGH-07` (local compiled Tailwind + vendored HTMX/Chart.js + tightened CSP), `HIGH-08` (filtered queries & inbox subquery optimization), `MED-05` (practice exam edit/delete UI + 0-question check + partial unique index), `MED-11` (deploy script update sequencing & migration tests), and `INFO-02` (refactoring `exam_service.py`) (**7 findings**).

6. **Which are genuinely difficult?**  
   Only future multi-tutor tenant isolation (`INFO-01` — scoping curriculum, exams, practice exams, conversations, settings, and student lists per `tutor_id`), which is **explicitly out of scope for initial launch** (**1 finding**).

7. **Does the application need architectural redesign?**  
   **No.** Synchronous FastAPI + SQLAlchemy 2.0 + Jinja2/HTMX + PostgreSQL 16 + Nginx on one VPS is the ideal simple architecture for 1 tutor and 100 students.

8. **What should be fixed before launch?**  
   All **7 production blockers (`HIGH-01`..`HIGH-07`)**, ideally plus **`HIGH-08`** (O(N) queries), **`MED-03`** (Nginx shared-NAT login limit), **`MED-09`/`MED-10`** (trivial UX/locale fixes), and passing **`./scripts/run_docker_tests.sh`** cleanly against PostgreSQL 16 + a tested **`restore.sh --dry-run` & real restore**.

9. **What can safely wait?**  
   `INFO-01` (multi-tutor support), `INFO-02` (splitting `exam_service.py` / archiving one-off `scripts/`), `LOW-04` (DB-level score `CHECK` constraints if app validation stays intact), and non-blocking enhancements in `MED-05` (practice exam edit/delete UI if tutor tests carefully before publishing).

10. **What would you deliberately NOT implement for this project's scale?**  
    Do **NOT** introduce Kubernetes, microservices, Redis, Celery/RQ/RabbitMQ, React/Next.js SPA rewrites, Elasticsearch, or multi-region PostgreSQL replication. All background needs (60s backup ticks or daily host cron, 4s/15s chat polls) run reliably in plain PostgreSQL + Nginx + Docker Compose once the SQL queries and static assets are cleaned up.
