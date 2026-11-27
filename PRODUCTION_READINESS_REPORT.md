# Valhalla Tutor — Production Readiness & Scalability Assessment Report

**Target Environment:** Single Ubuntu VPS (`2 CPU cores`, `4 GB RAM`), Docker Compose (`web` + `postgres:16-alpine`) + host Nginx reverse proxy  
**Expected Scale:** `2–3 tutors`, up to `100 students`  
**Assessment Mode:** Read-only code, configuration, schema, migration, infrastructure, and unit/workflow test audit (zero source/config edits performed)

---

## 1. Executive Summary

Valhalla Tutor already has several strong engineering foundations for a small single-VPS educational application: Argon2id password hashing (`app/core/security.py`), SHA-256-hashed opaque server-side session tokens in `HttpOnly; SameSite=Lax; Secure` cookies (`app/routers/auth.py`, `app/services/auth_service.py`), DB-backed CSRF enforcement across authenticated student/tutor routes (`app/core/dependencies.py`), parameterized SQLAlchemy 2.0 queries, Jinja2 autoescaping with zero `|safe` sinks in templates, path-traversal-hardened upload resolution (`app/core/storage.py`), solid core database constraints (`RESTRICT` audit retention, composite foreign key `fk_plan_assignments_study_plan_student`, partial unique index `uq_study_plans_student_published`), and non-root Docker execution (`appuser:10001`). Across `19` unit and SQLite workflow test files executable inside this sandbox, **all `105` tests passed**.

However, **the application is NOT safe to put in front of real students and 2–3 tutors in its current state**. Direct inspection revealed **five critical blockers** that guarantee immediate downtime, silent student data loss, multi-tutor breakage, XSS in the primary Persian (`fa`) locale, or total loss of all records on host/migration failure:

1. **Broken Nginx-to-Docker port routing (`CRIT-01`):** `docker-compose.yml` publishes `127.0.0.1:18000:8000`, while `nginx/valhalla.conf` proxies to `127.0.0.1:8000`, causing immediate `502 Bad Gateway` errors out of the box.
2. **Timed practice exam auto-submit wipes student answers (`CRIT-02`):** `runner.html` disables all `.choice-radio` inputs before calling `form.submit()`, omitting every checked answer from the HTTP POST payload; because `get_student_booklet_state` truncates `remaining_seconds` with `int()`, the browser frequently submits slightly before the server timer expires and overwrites previously auto-saved answers with `None`.
3. **2–3 tutor support fails by design and causes crashes (`CRIT-03`):** `provision_tutor` overwrites the existing tutor account when adding a second tutor; `Conversation` (`uq_conversations_student_id` + single `tutor_id`) locks each student to one tutor and raises `MessagePermissionError` (causing unhandled 500s on scheduler proposal approvals and partial-commit errors on calendar quick-move); and `/tutor/plans` isolates read visibility per `tutor_id` while `publish_study_plan` archives other tutors' plans.
4. **Zero automated, off-VPS, or tested backups (`CRIT-04`):** `backups/` contains only `.gitkeep`. PostgreSQL data (`postgres_data`) and uploaded PDFs/images (`uploads_data`) sit solely in local Docker volumes, while `scripts/entrypoint.sh` executes `alembic upgrade head` automatically on boot (`AUTO_MIGRATE=true`) without taking any pre-migration backup.
5. **XSS in Persian (`fa`) locale via placeholder injection (`CRIT-05`):** `app/core/i18n.py` (`localize_html_content`) replaces `<script>`/`<style>`/`<code>`/`<pre>` blocks with predictable markers `___VALHALLA_PROTECTED_{i}___` and later executes plain `html.replace(marker, p)` across the entire HTML response, allowing user-controlled text containing that literal token (e.g., inside messages, notes, or HTML attributes) to splice unescaped `<script>...</script>` HTML into `fa`-rendered pages.

The underlying **FastAPI + SQLAlchemy + PostgreSQL + Jinja2 + HTMX** architecture **is well suited** to `2–3 tutors` and `100 students` on a `2-core / 4 GB VPS`. No microservices, Redis, Celery, or Kubernetes are needed. Once the pre-launch blockers (`Phase A`, estimated at roughly `2–4 focused engineering days`) are fixed and tested against real PostgreSQL and Docker Compose, this exact stack can operate reliably within ~1.2–1.8 GB total RAM.

### Verification Scope & Unverified Boundaries

| Verification Check | Observed Result | Notes / Unverified Boundaries |
|---|---|---|
| Static source, SQL model, migration, template, Docker, Nginx inspection | Completed | Inspected all `app/core/*`, `app/models/*`, `app/services/*`, `app/routers/*`, all 19 `alembic/versions/*`, deployment configs, and critical templates |
| Non-`TestClient`, non-PG unit & workflow suite (`19` files) | **105 passed** (`11.45s`, `26` warnings) | Executed `.venv\Scripts\python.exe -m pytest ...` against SQLite / unit mocks |
| `tests/test_demo_generator.py` (`1` test) | **1 failed** (`psycopg2.OperationalError`) | Expected without live PostgreSQL (`localhost:15432` inaccessible in sandbox) |
| `tests/test_postgres_integration.py` (`5` tests) | **Unverified / Skipped** | Guarded by `skipif(not is_postgres_available())`; requires live PostgreSQL 16 |
| `TestClient` route & integration suite (`17` files, `117` tests) | **Unverified in sandbox** | Hangs in Windows sandbox at `TestClient(app)` (`tests/test_health.py::test_liveness_endpoint` stalled); must run in Linux/Docker before launch |
| `alembic upgrade head` (clean SQLite DB) | **Passed** -> `2c3d4e5f6a7b (head)` | Applied all 19 revisions cleanly |
| `alembic upgrade head --sql` (offline SQL generation) | **Failed** (`exit 1`) | Crashed at `0a1b2c3d4e5f` line 27 (`AttributeError` calling `.fetchall()` on `None`) |
| `alembic check` (model vs. migration drift) | **Failed** (`exit 1`) | Reported 3 missing FK indexes + unique constraint mismatch on `subjects` & `academic_tracks` |
| Load/stress testing, live Ubuntu VPS runtime, `pip-audit` CVE scan | **Unverified** | No network access or live multi-user container load test was performed |

---

## 2. Final Production Readiness Verdict

**Verdict:** **Not production-ready — moderate work required.**

Why this verdict (and not *"minor fixes"* or *"fundamental problems"*):
- The core domain modeling, authentication cryptography, CSRF model, and single-monolith SSR architecture do **not** need a redesign (`OPT-01`–`OPT-05` confirm enterprise middleware is unnecessary here).
- However, production cannot safely launch with only a quick config tweak: resolving multi-tutor data/ownership bugs (`CRIT-03`), fixing the timed exam data-loss bug (`CRIT-02`), patching `fa` locale XSS (`CRIT-05`), fixing port alignment (`CRIT-01`), implementing and verifying off-VPS automated backups (`CRIT-04`), tuning container/DB memory caps (`HIGH-02`), and fixing the worst event-loop-blocking `async def` endpoints + N+1/full-table scans (`HIGH-04`, `HIGH-08`) plus executing the unverified `117` `TestClient` and `6` PostgreSQL tests requires deliberate, multi-file **moderate work** before real students log in.

---

## 3. Score Table

| Area | Score | Summary Rationale |
|---|---:|---|
| Functional reliability | **4 / 10** | Strong server locking/guards in several paths, but practice exam auto-submit wipes saved answers (`CRIT-02`), 2–3 tutor flows overwrite/fail (`CRIT-03`), reminder claiming lacks locking (`HIGH-06`), naive exam deadlines drift 3.5h (`HIGH-09`), and uncaught exceptions crash redirects (`HIGH-07`). |
| Security | **5 / 10** | Solid Argon2id, SHA-256 cookie sessions, CSRF dependency, ORM parameterization, and path traversal checks; severely undermined by `fa` placeholder XSS (`CRIT-05`), missing upload magic-byte checks (`HIGH-04`), `'unsafe-inline' 'unsafe-eval'` CSP + external CDNs without SRI (`HIGH-03`), and split-worker/timing auth weaknesses (`HIGH-05`). |
| Database integrity | **7 / 10** | Well-normalized schema with strong composite FKs, partial unique index, `RESTRICT` audit protections, and linear Alembic chain; loses points for `uq_conversations_student_id` blocking multiple tutors, `alembic check` index/constraint drift (`EASY-02`), offline migration crash (`EASY-03`), and unbounded session growth. |
| Performance at intended scale | **6 / 10** | Stack easily handles 100 students / 2–3 tutors in principle, but full-table exam queries (`exam_service`, `practice_exam_service`), `2N+1` inbox queries, 8+ blocking `async def` routes (`HIGH-04`, `HIGH-08`), 3–4x duplicate polling (`HIGH-06`, `EASY-09`), and Tailwind Play CDN (`HIGH-03`) degrade concurrency on 2 cores. |
| Infrastructure and deployment | **4 / 10** | Non-root Dockerfile, healthchecks, log rotation, and `unless-stopped` are good, but shipped Compose (`18000`) and Nginx (`8000`) ports conflict (`CRIT-01`), RAM caps (`2G+2G=4G`) risk OOM (`HIGH-02`), demo PDFs bake into `/app/uploads`, and CDN dependency violates offline resilience. |
| Backup and recovery | **1 / 10** | Bind mount and sample manual doc commands exist, but zero automation, zero off-VPS copies, zero restore testing, and `AUTO_MIGRATE=true` runs schema upgrades with no pre-migration dump (`CRIT-04`). |
| Maintainability | **6 / 10** | Clear `routers`/`services`/`models` layout and tests, but `exam_service.py` (3,079 lines) and `plan_service.py` (1,110 lines) are heavy, regex HTML localization (`i18n.py`) is brittle, dead `SECRET_KEY` misleads admins, and error redirects duplicate boilerplate. |
| Test coverage and confidence | **5 / 10** | `105` unit/SQLite tests passed reliably; however `117` `TestClient` tests and `6` PostgreSQL tests could not run in this sandbox, no `pip-audit` or load tests ran, and `CRIT-02` slipped past existing tests. |

- **Overall Production Readiness Score:** **4.5 / 10** *(not an arithmetic mean — intentionally weighted downward so silent data-loss, broken multi-tutor behavior, port outage, XSS, and zero backups cannot hide behind good ORM/auth hygiene).*
- **Confidence Level in Assessment:** **Medium-High** — very high on code, schema, security, and deployment configuration (read end-to-end); **unverified** on runtime HTTP integration (`117` `TestClient` tests), live PostgreSQL 16 concurrency (`6` tests), actual load latency metrics, and dependency CVEs.
- **Ready for Real Users?** **No** (until Phase A fixes and full test verification are completed).
- **Can It Comfortably Operate on 2 Cores / 4 GB RAM?** **Yes** — once `docker-compose.yml` memory limits are lowered (`768M` DB + `1G` Web), N+1 / full-table exam queries + blocking `async def` handlers are fixed, and duplicate navbar polling is deduplicated.
- **Biggest Remaining Risks:** Student exam answer loss (`CRIT-02`), 2–3 tutor breakage (`CRIT-03`), permanent data loss on VPS/migration failure (`CRIT-04`), Persian (`fa`) XSS (`CRIT-05`), unverified `117` HTTP route + `6` PostgreSQL tests, and external CDN outages (`HIGH-03`).

---

## 4. Infrastructure Suitability: 2 Cores / 4 GB RAM

Assuming a typical Ubuntu 22.04/24.04 VPS running host Nginx + Certbot + Docker Engine + `valhalla_db` (`postgres:16-alpine`) + `valhalla_web` (`WEB_CONCURRENCY=2` Uvicorn workers):

### Estimated Memory & CPU Budget (for 2–3 tutors, up to 100 students)

| Component | Current Configured Cap | Expected Idle RAM | Expected Peak RAM (25–50 active students) | Notes & Evidence |
|---|---:|---:|---:|---|
| Ubuntu OS + systemd + Docker daemon | None | ~300–450 MB | ~450–550 MB | Kernel page cache uses remaining free RAM |
| Host Nginx + Certbot | None | ~20–40 MB | ~40–80 MB | Terminates TLS, `limit_req_zone` 10m, gzip level 5 |
| `postgres:16-alpine` (`valhalla_db`) | `2G` limit (`256M` resv.) | ~60–120 MB | ~250–450 MB | Currently untuned defaults; `768M` hard cap + `shared_buffers=256MB` fits easily |
| `valhalla_web` (`WEB_CONCURRENCY=2` Uvicorn) | `2G` limit (`256M` resv.) | ~180–260 MB | ~350–650 MB | Python 3.12 + FastAPI/SQLAlchemy/Argon2 across 2 workers + 25 MB multipart uploads |
| Temporary overhead (`pg_dump` / `tar` / upload spikes) | — | — | ~100–250 MB | Must preserve headroom so OOM killer never triggers |
| **Total Expected Stack Usage** | **`4G` combined caps (`HIGH-02`)** | **~560–870 MB** | **~1.2–2.0 GB** | **~2.0+ GB free headroom for OS page cache & spikes once caps are fixed** |

*(Note: RAM and CPU figures above are engineering estimates derived from inspecting `Dockerfile`, `docker-compose.yml`, `scripts/entrypoint.sh`, `requirements.txt`, and `nginx/valhalla.conf`; live container RSS was not measured because containers were not started in the sandbox.)*

**Key finding on 2 cores / 4 GB:** The hardware is **sufficient**, **not** undersized—**if and only if** three software/config flaws are corrected:
1. Container memory limits in `docker-compose.yml` (`2G + 2G = 4G`) leave zero budget for OS/Nginx/host tasks if Postgres or Python spikes (`HIGH-02`).
2. Blocking synchronous file/DB calls inside `async def` handlers (`HIGH-04`, `HIGH-08`) plus full-table exam queries (`exam_service.py:1260-1274`) waste CPU and memory on `WEB_CONCURRENCY=2` workers.
3. Argon2id password verification (`auth_service.py`) is CPU/memory-hard (~64 MiB default in `argon2-cffi` per concurrent hash verification); with 50–100 students logging in over a short exam window across 2 Uvicorn workers, serialized/queued logins take a few seconds smoothly **unless** Nginx blocks shared Wi-Fi IPs with `limit_req` on `GET /auth/login` (`HIGH-05`).

---

## 5. Critical Blockers (Category 1 — Must Fix Before Production)

### `CRIT-01` — Nginx vs. Docker Compose Port Mismatch Causes Total Outage (`502 Bad Gateway`)
- **Unique finding ID:** `CRIT-01`
- **Severity:** Critical
- **Category:** Category 1 — Critical blocker
- **Exact file and relevant function/configuration:** `docker-compose.yml` lines 44–45 (`services.web.ports`), `nginx/valhalla.conf` lines 5–8 (`upstream valhalla_app`), `docs/DEPLOYMENT.md` lines 9, 110, 130
- **Evidence from the implementation:**
  - `docker-compose.yml:45` binds the web container on host loopback as `"127.0.0.1:18000:8000"`.
  - `nginx/valhalla.conf:6` points upstream to `server 127.0.0.1:8000 fail_timeout=10s max_fails=3;`.
  - `docs/DEPLOYMENT.md` similarly instructs operators to curl `http://127.0.0.1:8000/health/db` and configure Nginx against port `8000`.
- **Real-world impact:** Out-of-the-box deployment leaves Nginx unable to reach the container (`502 Bad Gateway` for every user) or silently routes student traffic to another application listening on `127.0.0.1:8000` on a shared VPS.
- **Whether it actually matters for this project's scale:** Yes — completely prevents launch at any scale.
- **Recommended solution:** Update `nginx/valhalla.conf:6` and `docs/DEPLOYMENT.md` to `127.0.0.1:18000` (keeping `18000` avoids colliding with other apps on port `8000` on the shared Ubuntu VPS), or consistently expose `${PORT:-18000}:8000`.
- **Estimated complexity:** Very easy
- **Whether it blocks production deployment:** Yes

### `CRIT-02` — Practice Exam Timed Auto-Submission Silently Wipes Saved Booklet Answers
- **Unique finding ID:** `CRIT-02`
- **Severity:** Critical (Data loss / Incorrect exam grading)
- **Category:** Category 1 — Critical blocker
- **Exact file and relevant function/configuration:**
  - `app/templates/student/practice_exams/runner.html` lines 269–299 (`triggerAutomaticSubmission`, `updateTimer`)
  - `app/routers/student_practice_exams.py` lines 420–422 (`post_submit_booklet_and_advance`)
  - `app/services/practice_exam_service.py` lines 498–499 (`get_student_booklet_state`), lines 657 & 688 (`submit_booklet_answers`)
- **Evidence from the implementation:**
  - `get_student_booklet_state` (`practice_exam_service.py:498-499`) computes `remaining_seconds = max(0, int((exp - now).total_seconds()))`, truncating up to `0.999s` compared to server `exp` (and client clock ticks during download/render can trigger slightly early).
  - When `remaining <= 0`, `triggerAutomaticSubmission()` (`runner.html:273`) runs `document.querySelectorAll('.choice-radio').forEach(r => r.disabled = true);`, awaits pending AJAX auto-saves, and then calls `form.submit()` (`lines 279-282`).
  - Browsers omit `disabled` inputs from HTML `<form>` submissions.
  - On receipt, while server `now < exp` (`is_time_expired` is False at `practice_exam_service.py:657`), `post_submit_booklet_and_advance` (`student_practice_exams.py:420-422`) constructs `answers[q.question_number] = int(val) if val and str(val).isdigit() else None` for every question in the booklet, and `submit_booklet_answers` (`practice_exam_service.py:688`) sets `ans_rec.selected_choice = choice` — overwriting every auto-saved answer with `None`!
- **Real-world impact:** Students completing a timed practice exam see all their auto-saved choices wiped when the timer hits `00:00` and receive an all-unanswered score (or wrong booklet results) permanently stored in `student_practice_answers`.
- **Whether it actually matters for this project's scale:** Yes — practice exams with booklets & timers are a core user-facing feature.
- **Recommended solution:** Remove `r.disabled = true` in `runner.html:273` (use CSS `pointer-events-none opacity-60` and block `change` events with `if (isSubmitting) return` cleanly), **and** harden `post_submit_booklet_and_advance` / `submit_booklet_answers` so missing form fields during booklet final submit do not overwrite previously auto-saved `selected_choice` rows unless an explicit `"clear"` signal was submitted. Add a regression test asserting auto-submit preserves saved answers even with `remaining_seconds` skew.
- **Estimated complexity:** Easy
- **Whether it blocks production deployment:** Yes

### `CRIT-03` — Multi-Tutor Architecture (`2–3 Tutors`) Is Broken Across CLI, Chat, Scheduler, and Study Plans
- **Unique finding ID:** `CRIT-03`
- **Severity:** Critical (Data overwrite / Unhandled 500s / Broken multi-tutor workflows)
- **Category:** Category 1 — Critical blocker
- **Exact file and relevant function/configuration:**
  - `app/services/tutor_provision.py` lines 20–33 (`provision_tutor`)
  - `app/models/message.py` lines 17, 25–37 (`Conversation`, `uq_conversations_student_id`)
  - `app/services/message_service.py` lines 42–44 (`get_or_create_conversation`), lines 296–298 (`list_tutor_conversations`)
  - `app/services/scheduler_service.py` lines 507–524 (`approve_weekly_proposal`), lines 556–578 (`quick_move_meeting`); `app/routers/tutor_scheduler.py` lines 343–345, 348–385
  - `app/routers/tutor_plans.py` (filters reads by `tutor_id=current_user.id`) vs. `app/services/plan_service.py` lines 420–432 (`publish_study_plan`)
- **Evidence from the implementation:**
  - **CLI overwrite:** `provision_tutor` (`tutor_provision.py:21-25`) falls back to `db.query(User).filter(User.role == UserRole.TUTOR).first()` whenever `username` doesn't exist yet, overwriting the first tutor's `username`, `hashed_password`, `email`, and `full_name` instead of inserting a 2nd/3rd tutor.
  - **Chat exclusivity + scheduler crashes:** `Conversation` only permits one row per student (`uq_conversations_student_id`) with one `tutor_id`. If Tutor A ever opens/schedules with Student X, `get_or_create_conversation(..., tutor_id=tutor_b.id)` raises `MessagePermissionError("Conversation is owned by another tutor.")` (`message_service.py:43-44`). Consequently, Tutor B calling `post_approve_proposal` (`tutor_scheduler.py:343`, no try/except for `MessagePermissionError`) triggers HTTP 500; Tutor B calling `quick_move_meeting` commits `reschedule_meeting` at line 556 and *then* fails on `get_or_create_conversation` at line 569, returning HTTP 400 `"Unable to reschedule meeting."` even though the meeting move already committed!
  - **Study plan split-brain:** All `/tutor/students` profiles, subjects, books, videos, and exams are shared across tutors, yet `/tutor/plans` restricts reading/editing to `tutor_id == current_user.id`, while `publish_study_plan` (`plan_service.py:420-432`) archives *other tutors'* active published plans for that student.
- **Real-world impact:** Cannot cleanly onboard 2–3 tutors; Tutor #2 silently overwrites Tutor #1 via CLI, and even if added manually in SQL, Tutors 2–3 crash scheduler approvals, suffer partial-commit errors on calendar drag-drop, cannot chat with students messaged by another tutor, and cannot manage another tutor's draft/active study plan.
- **Whether it actually matters for this project's scale:** Yes — `2–3 tutors` is an explicit Day-1 requirement.
- **Recommended solution:**
  1. Fix `provision_tutor` to match strictly on `clean_username` (never fall back to overwriting an unrelated `UserRole.TUTOR`).
  2. Define the shared-academy collaboration model for 2–3 tutors: allow any active `TUTOR` to participate in a student's conversation (retaining `sender_id` attribution on every `Message` and setting `show_sender_name=True` in `message_bubble.html`), wrap `quick_move_meeting` + notification inside one transaction or handle notification cleanly, and allow any active tutor to view/edit/publish shared student study plans while preserving `tutor_id` / `performed_by_id` creator/actor audit attribution. *(Note: `TutorMeeting` & `WeeklyScheduleProposal` can stay per-tutor calendar schedules, as each tutor has their own calendar).*
- **Estimated complexity:** Moderate
- **Whether it blocks production deployment:** Yes

### `CRIT-04` — Zero Automated Backups, Zero Off-VPS Storage, No Restore Verification, and Unguarded `AUTO_MIGRATE`
- **Unique finding ID:** `CRIT-04`
- **Severity:** Critical (Permanent data loss)
- **Category:** Category 1 — Critical blocker
- **Exact file and relevant function/configuration:**
  - `backups/` (only `.gitkeep`)
  - `docker-compose.yml` lines 13–15, 55–56, 88–90 (`postgres_data`, `uploads_data`, `./backups`)
  - `scripts/entrypoint.sh` lines 40–46 (`AUTO_MIGRATE`)
  - `docs/DEPLOYMENT.md` lines 118–152
- **Evidence from the implementation:** No backup script, cron job, systemd timer, or off-site sync exists in the repository; `backups/` is empty apart from `.gitkeep`. All persistent data sits inside two local Docker volumes (`postgres_data` and `uploads_data`), while `scripts/entrypoint.sh:40-43` automatically executes `alembic upgrade head` on container start (`AUTO_MIGRATE=true` in `.env.example:28`) with zero automatic pre-migration snapshot. No tested restore procedure exists.
- **Real-world impact:** Any VPS disk loss, accidental `DELETE`/truncate, failed Alembic migration mid-deploy, filesystem corruption, or `docker compose down -v` causes total irreversible loss of student grades, plans, chat history, and uploaded PDFs/images.
- **Whether it actually matters for this project's scale:** Yes — losing an entire 100-student cohort's academic records is catastrophic regardless of user count.
- **Recommended solution:** Create and install a simple host-level daily backup script (Ubuntu `cron` or systemd timer) running `pg_dump -Fc` and archiving `/var/lib/docker/volumes/...` or `docker compose exec -T web tar -czf ... uploads`, keep rolling local snapshots (`7–14` days), sync encrypted backups off-VPS (e.g. `restic` or `rclone` to remote object storage / secondary server), set `AUTO_MIGRATE=false` in production `.env` (using an explicit `backup -> migrate -> restart` update script), and perform + document one real restore test into a clean database + uploads volume before go-live.
- **Estimated complexity:** Easy
- **Whether it blocks production deployment:** Yes

### `CRIT-05` — Stored/Reflected XSS in Persian (`fa`) Locale via HTML Placeholder Injection (`___VALHALLA_PROTECTED_{i}___`)
- **Unique finding ID:** `CRIT-05`
- **Severity:** Critical (Stored & reflected XSS -> CSRF token theft & tutor/student impersonation)
- **Category:** Category 1 — Critical blocker
- **Exact file and relevant function/configuration:**
  - `app/core/i18n.py` lines 625–630 and 692–696 (`localize_html_content`)
  - `app/core/templates.py` lines 55–66 (`ValhallaTemplates.TemplateResponse`)
- **Evidence from the implementation:** On every HTML page when `valhalla_locale=fa`, `ValhallaTemplates.TemplateResponse` post-processes the rendered Jinja output through `localize_html_content`:
  1. `i18n.py:625-630` captures `<script>`, `<style>`, `<code>`, `<pre>` tags into `preserved[]` and replaces them with predictable markers `f"___VALHALLA_PROTECTED_{len(preserved)-1}___"`.
  2. `i18n.py:693-694` restores them using naive string replacement across the entire HTML document: `html = html.replace(f"___VALHALLA_PROTECTED_{i}___", p)`.
  Because `___VALHALLA_PROTECTED_0___`, `___VALHALLA_PROTECTED_1___`, etc. contain no HTML metacharacters (`<`, `>`, `"`), Jinja2 autoescaping leaves user input containing that string intact. When rendered inside `value="{{ ... }}"` (e.g. form inputs, query params like `?err=...`, chat/assignment/exam strings), replacing the token with `<script src="..."></script>` or inline `<script>...</script>` injects raw double quotes and `<script>` tags straight out of attribute quotes into the DOM!
- **Real-world impact:** A malicious student (or attacker crafting a `?err=___VALHALLA_PROTECTED_3___` link) can break out of HTML attributes/text on Persian (`fa`) pages, read the victim's `<meta name="csrf-token">` or execute arbitrary authenticated requests as a tutor or fellow student.
- **Whether it actually matters for this project's scale:** Yes — Persian (`fa` / `Asia/Tehran`) is a primary target locale.
- **Recommended solution:** Immediately replace the fixed prefix `"___VALHALLA_PROTECTED_"` with an unpredictable per-request cryptographic nonce (`secrets.token_hex(16)`) or refuse/escape conflicting occurrences (and longer-term replace regex HTML rewriting, see `MOD-05`).
- **Estimated complexity:** Very easy
- **Whether it blocks production deployment:** Yes

---

## 6. High-Priority Issues (Category 2)

### `HIGH-01` — Weak Hardcoded Fallback Database Password, Dead `SECRET_KEY`, and Missing Production Config Guards
- **Unique finding ID:** `HIGH-01`
- **Severity:** High
- **Category:** Category 2 — High-priority fix
- **Exact file and relevant function/configuration:** `app/core/config.py` lines 23, 28 (`Settings`), `.env.example` lines 17, 22, `.env` lines 17, 21
- **Evidence from the implementation:** `Settings` defaults to `POSTGRES_PASSWORD = "postgres"` and `SECRET_KEY = "dev-secret-key-please-change-in-production-min-32-chars"`; `git grep SECRET_KEY` shows `SECRET_KEY` is unused everywhere in `app/` and `scripts/`, and there is no startup check preventing `ENVIRONMENT=production` from starting with `DEBUG=True` or default/placeholder secrets (`replace_with_strong_random_db_password`).
- **Real-world impact:** A misconfigured deployment silently boots with weak database credentials or `DEBUG=True` SQL/trace leakage (`database.py:12` sets `echo=settings.DEBUG`).
- **Whether it actually matters for this project's scale:** Yes — standard operational safeguard against human deploy mistakes.
- **Recommended solution:** Add a Pydantic validator / startup check in `app/core/config.py` (or `app/main.py` lifespan) that aborts startup when `ENVIRONMENT == "production"` if `DEBUG` is `True` or `POSTGRES_PASSWORD` equals `"postgres"` / `"replace_with_strong_random_db_password"` / empty; remove or explicitly document `SECRET_KEY` rather than leaving dead security config.
- **Estimated complexity:** Very easy
- **Whether it blocks production deployment:** Recommended before launch

### `HIGH-02` — Container Memory Limits (`2G` + `2G` = `4G`) Exhaust Host RAM + Untuned PostgreSQL & Pool Bounds
- **Unique finding ID:** `HIGH-02`
- **Severity:** High
- **Category:** Category 2 — High-priority fix
- **Exact file and relevant function/configuration:** `docker-compose.yml` lines 29–34, 74–79; `app/core/database.py` lines 9–13 (`create_engine`)
- **Evidence from the implementation:** `db` and `web` each set `deploy.resources.limits.memory: 2G` (`4G` total = 100% of the VPS RAM), leaving zero reserved memory margin for Ubuntu kernel/OS, Docker daemon, host Nginx, or backup processes (`pg_dump`/`tar`), with zero CPU limits (`cpus`) and default PostgreSQL 16 settings (`max_connections=100`, default `shared_buffers`). `database.py:9-13` uses SQLAlchemy default pooling (`pool_size=5, max_overflow=10` = up to `15` connections per worker = `30` across `WEB_CONCURRENCY=2`, scaling linearly if workers increase).
- **Real-world impact:** Concurrent upload/analytics activity can drive combined RSS past free host RAM and trigger the Linux OOM killer on PostgreSQL or Nginx.
- **Whether it actually matters for this project's scale:** Yes — directly governs stability on a **2-core / 4 GB VPS**.
- **Recommended solution:** Set `db` memory limit to `768M` (`reservations: 256M`) and `web` memory limit to `1024M` (`reservations: 256M`), configure Postgres (`-c shared_buffers=256MB -c effective_cache_size=768MB -c work_mem=4MB -c max_connections=50`), and set explicit SQLAlchemy `pool_size=5, max_overflow=5, pool_recycle=1800` in `database.py`.
- **Estimated complexity:** Easy
- **Whether it blocks production deployment:** Recommended before launch

### `HIGH-03` — Frontend Hard-Depends on 4 Unpinned External Public CDNs (No SRI) and Forces `'unsafe-inline' 'unsafe-eval'` CSP
- **Unique finding ID:** `HIGH-03`
- **Severity:** High
- **Category:** Category 2 — High-priority fix
- **Exact file and relevant function/configuration:** `app/templates/base.html` lines 9–13; Chart.js CDN in `student/exams/analytics.html` & `tutor/exams/student_analytics.html`; `app/main.py` lines 64–76 (`add_security_headers`)
- **Evidence from the implementation:** `base.html:9-12` loads `https://cdn.tailwindcss.com` (the in-browser Tailwind compiler JS), `https://unpkg.com/htmx.org@1.9.12`, and `https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/Vazirmatn-font-face.css` without `integrity="..."` SRI attributes, while `analytics.html`/`student_analytics.html` load Chart.js from `cdn.jsdelivr.net`. Because `cdn.tailwindcss.com` compiles styles dynamically with JS, `app/main.py:66` allows `script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://unpkg.com https://cdn.jsdelivr.net`.
- **Real-world impact:** Any upstream CDN outage or regional DNS/network throttling (particularly relevant for `Asia/Tehran` default deployments) strips all layout styling and breaks HTMX actions across the entire app; third-party script compromise or `'unsafe-eval'` weakens XSS defenses; mobile browsers burn CPU compiling Tailwind on every page load.
- **Whether it actually matters for this project's scale:** Yes — affects 100% of users on every page load.
- **Recommended solution:** Vendor `htmx.min.js`, `chart.umd.min.js`, and Vazirmatn font files directly into `app/static/` and replace `cdn.tailwindcss.com` with a precompiled `tailwind.css` generated at Docker build time via standalone Tailwind CLI (`tailwindcss` binary — no Node runtime needed in production image), then remove third-party CDNs and `'unsafe-eval'` from CSP in `app/main.py`. *(Removing `'unsafe-inline'` requires extracting inline template `<script>` blocks into static files as a follow-up).*
- **Estimated complexity:** Moderate
- **Whether it blocks production deployment:** Strongly recommended before launch (especially for `Asia/Tehran` network reliability)

### `HIGH-04` — File Upload Validation Trusts Client Metadata (No Magic Bytes) and Blocks `async def` Event Loops
- **Unique finding ID:** `HIGH-04`
- **Severity:** High
- **Category:** Category 2 — High-priority fix
- **Exact file and relevant function/configuration:**
  - `app/core/storage.py` lines 29–88 (`save_uploaded_file`)
  - `app/routers/tutor_practice_exams.py` lines 176–205 (`post_upload_booklet`)
  - `app/routers/tutor_historical_exams.py` lines 115–160 (`post_create_historical_exam`)
  - `app/routers/student_exams.py` lines 142–220 (`post_submit_result`), lines 312–380 (`post_edit_result`)
- **Evidence from the implementation:**
  - `save_uploaded_file` (`storage.py:43-54`) only verifies extension (`ext in allowed_exts`) and skips MIME rejection whenever `content_type` is empty or `application/octet-stream`, without inspecting magic bytes (`%PDF-`, PNG, JPEG, WEBP headers).
  - All four file upload routes are declared `async def`, yet synchronously call `save_uploaded_file` (chunked blocking `file.file.read` + disk write) and synchronous SQLAlchemy queries directly inside the Uvicorn worker's single asyncio event loop thread.
- **Real-world impact:** Any file (polyglot/script/corrupt binary) renamed `.pdf` or `.png` passes validation; concurrent 10–25 MB uploads stall an entire Uvicorn worker (`1` of only `2` workers), freezing unrelated students' requests on that worker.
- **Whether it actually matters for this project's scale:** Yes — peak post-exam period has students uploading report cards concurrently onto a 2-worker / 2-core VPS.
- **Recommended solution:** Check leading magic bytes (`b"%PDF-"` for PDFs, `b"\x89PNG\r\n\x1a\n"`, `b"\xff\xd8\xff"`, `RIFF....WEBP` for images) in `save_uploaded_file`, ensure `Content-Disposition: attachment` / `X-Content-Type-Options: nosniff` on downloads (already present via `FileResponse(..., filename=...)` + middleware), and convert upload handlers to synchronous `def` (or run disk writes via `run_in_threadpool` if `await request.form()` is required).
- **Estimated complexity:** Easy
- **Whether it blocks production deployment:** Recommended before launch

### `HIGH-05` — Authentication Brute-Force & UX Gaps: Split-Worker Memory Rate Limiter, Timing Enumeration, Case-Sensitive Login, and Nginx Blocking `GET /auth/login`
- **Unique finding ID:** `HIGH-05`
- **Severity:** High
- **Category:** Category 2 — High-priority fix
- **Exact file and relevant function/configuration:**
  - `app/core/rate_limit.py` lines 13–53 (`LoginRateLimiter`, `login_limiter`), lines 128–149
  - `app/services/auth_service.py` lines 20–34 (`authenticate_user`)
  - `app/services/user_service.py` line 47 (`create_student` `.lower()`), `app/services/tutor_provision.py` line 17 (`.lower()`)
  - `nginx/valhalla.conf` lines 2, 55–56 (`limit_req zone=valhalla_auth`)
- **Evidence from the implementation:**
  - `LoginRateLimiter` keeps attempts in process-local RAM (`self.attempts`), so `WEB_CONCURRENCY=2` halves enforcement (`10/min/IP` combined) and resets on restart; keys are only evicted when the same key is reused (slow unbounded memory growth under distributed scans); no per-username throttle exists.
  - `authenticate_user` (`auth_service.py:28-34`) returns immediately on unknown username/inactive account without running Argon2 `verify_password`, creating a measurable timing oracle (`<1ms` vs `~50–150ms`) for username enumeration.
  - Usernames are normalized `.lower()` on creation (`user_service.py:47`, `tutor_provision.py:17`), whereas `authenticate_user` queries `User.username == identifier.strip()` case-sensitively, rejecting valid users who type `Student1`.
  - `nginx/valhalla.conf:55-56` applies `5r/m burst=10 nodelay` to `location /auth/login` for **both `GET` and `POST`**, risking false `503` blocks when multiple students behind one school/home NAT open the login page at the start of an exam.
- **Real-world impact:** Legitimate students fail to log in on case-mismatched usernames or get throttled opening the login page over shared Wi-Fi, while attackers can enumerate usernames by response time or spray passwords per account across rotating IPs.
- **Whether it actually matters for this project's scale:** Yes — shared classroom/family Wi-Fi IPs and student account hygiene matter immediately at 100 students.
- **Recommended solution:** Lowercase `identifier` in `authenticate_user` and perform a constant-cost dummy Argon2 verify when no user matches; apply Nginx `limit_req` only on `POST` (`limit_except GET HEAD { ... }` or dedicated login burst), add a simple PostgreSQL-backed failed-attempt counter / cooldown per `(username)` (or on `users` table without needing Redis), and prune expired IP entries in `LoginRateLimiter`.
- **Estimated complexity:** Moderate
- **Whether it blocks production deployment:** Fix auth lookup/timing + Nginx `GET` rule before launch; DB-backed per-account backoff before or shortly after launch.

### `HIGH-06` — Meeting Reminder Query Lacks Row Lock (`FOR UPDATE SKIP LOCKED`), Fires Double Navbar Pollers, and References Missing `#modal-container`
- **Unique finding ID:** `HIGH-06`
- **Severity:** High
- **Category:** Category 2 — High-priority fix
- **Exact file and relevant function/configuration:**
  - `app/services/meeting_service.py` lines 450–489 (`get_due_reminders`)
  - `app/templates/base.html` lines 273, 307
  - `app/templates/tutor/calendar/partials/reminder_indicator.html` line 1 (`#tutor-reminders-widget`)
  - `app/templates/tutor/calendar/calendar.html` line 86 (`#modal-container`)
- **Evidence from the implementation:**
  - `get_due_reminders` docstring states *"atomically trigger pending due reminders... across multiple worker processes"*, yet lines 461–477 run a plain `SELECT` without `.with_for_update(skip_locked=True)`.
  - `base.html:273` (`#tutor-reminders-container`) and `base.html:307` (`#tutor-reminders-mobile`) both execute `hx-get="/tutor/reminders/unread" hx-trigger="load"`, placing two duplicate `#tutor-reminders-widget` polling blocks (`every 30s`) in every tutor page DOM.
  - `#modal-container` exists only in `calendar.html:86`, breaking HTMX modal interactions triggered from navbar reminders on other tutor pages.
- **Real-world impact:** Concurrent duplicate reminder requests on every tutor page load race to mutate `triggered_at`, pollute the DOM with duplicate `#tutor-reminders-widget` IDs, and fail silently when tutors open reminder modals outside `/tutor/calendar`.
- **Whether it actually matters for this project's scale:** Yes — affects 2–3 tutors on every authenticated page.
- **Recommended solution:** Render a single responsive reminder widget (and place `#modal-container` in `base.html` if used globally), and claim `triggered_at` using an atomic `UPDATE ... WHERE triggered_at IS NULL` or `with_for_update(skip_locked=True, of=MeetingReminder)` on PostgreSQL.
- **Estimated complexity:** Easy
- **Whether it blocks production deployment:** Recommended before/soon after launch

### `HIGH-07` — Uncaught Exceptions Return HTTP 500s and Unquoted Error Strings Crash `RedirectResponse` Headers
- **Unique finding ID:** `HIGH-07`
- **Severity:** High
- **Category:** Category 2 — High-priority fix
- **Exact file and relevant function/configuration:**
  - `app/routers/tutor_books.py` lines 211, 241, 260
  - `app/routers/tutor_videos.py` lines 215, 245, 264
  - `app/routers/tutor_tracks.py` lines 179, 198, 203–218 (`post_delete_track`)
  - `app/routers/tutor_plans.py` lines 103, 429; `app/routers/tutor_scheduler.py` lines 329, 343
  - `app/services/academic_service.py` (`delete_track` omits `PracticeExam` FK `RESTRICT` check); `app/services/message_service.py:59-70`
- **Evidence from the implementation:**
  - `tutor_books.py:211,241,260`, `tutor_videos.py:215,245,264`, and `tutor_tracks.py:179,198,216` build `RedirectResponse(url=f"...?err={str(exc)}")` without URL-encoding (`quote(..., safe="")`); multi-line SQLAlchemy errors crash Starlette HTTP header serialization with newline header exceptions (`ValueError`), and single-line errors leak internal exception text in browser URLs.
  - `post_delete_track` catches `(TrackInUseError, TrackNotFoundError)`, yet `PracticeExam.academic_track_id` (`app/models/practice_exam.py:36`) has `ondelete="RESTRICT"` and `academic_service.delete_track` does not check for referencing practice exams, causing an unhandled `IntegrityError` 500.
  - `tutor_plans.py:103, 429` and `tutor_scheduler.py:329, 343` allow domain exceptions (`PlanValidationError` / `SchedulerError` / `MessagePermissionError`) to escape as 500s; `get_or_create_conversation` (`message_service.py:59-70`) does not catch `IntegrityError` on concurrent creation.
- **Real-world impact:** Ordinary tutor workflows (deleting a track tied to a practice exam, double-clicking chat creation, invalid plan edits) produce raw 500 crashes instead of clean validation banners.
- **Whether it actually matters for this project's scale:** Yes — affects daily tutor administration.
- **Recommended solution:** Check `PracticeExam` references in `delete_track`, handle `IntegrityError` idempotently in `get_or_create_conversation` / `create_student`, wrap route service exceptions cleanly, and always URL-encode user-safe error messages (`quote(safe_msg, safe="")`).
- **Estimated complexity:** Easy
- **Whether it blocks production deployment:** Recommended before/soon after launch

### `HIGH-08` — Full-Table Exam Queries, `2N+1` Tutor Inbox Queries, and Remaining Sync-Blocking `async def` Routes
- **Unique finding ID:** `HIGH-08`
- **Severity:** High (Latency & RAM degradation as data grows)
- **Category:** Category 2 — High-priority fix
- **Exact file and relevant function/configuration:**
  - `app/services/exam_service.py` lines 1260–1274 (`get_student_available_exams`)
  - `app/services/practice_exam_service.py` lines 322–345 (`get_student_available_practice_exams`)
  - `app/services/message_service.py` lines 315–340 (`list_tutor_conversations`) + `app/templates/tutor/messages/inbox.html:39` (`every 15s`)
  - Sync DB inside `async def`: `app/routers/tutor_scheduler.py:129`, `app/routers/tutor_exams.py:334, 543, 608, 794` (plus upload routes in `HIGH-04`)
- **Evidence from the implementation:**
  - `get_student_available_exams` loads **every `ExamSession`** and eager-loads **all students'** `results`, `subject_results`, and `group_results` across the database before filtering for one `student_id` in Python (`O(students * sessions)` memory & CPU per student page load).
  - `get_student_available_practice_exams` eager-loads all `PracticeExam` rows and all students' `attempts`, then triggers N+1 lazy loads checking `assignments` per exam.
  - `list_tutor_conversations` executes 1 conversation query + `2N` per-student queries (latest message + unread count) — `201` SQL queries for `100` students on every open and every `15s` HTMX auto-refresh in `inbox.html:39`.
  - Multiple `async def` router handlers parse form data and execute blocking SQLAlchemy queries on the asyncio event loop thread.
- **Real-world impact:** Over a semester of weekly exams (e.g., 25 exams x 100 students = 2,500+ result trees x ~6 subject/group rows), opening `/student/exams` simultaneously for 25–50 students pulls tens of thousands of ORM objects into Python per burst on 2 cores, while 2–3 tutors with open `/tutor/messages` tabs generate hundreds of queries every 15s and sync `async def` handlers freeze event-loop concurrency.
- **Whether it actually matters for this project's scale:** Yes — specifically degrades at `50–100 students` over months of real exam history on `2 cores / 4 GB RAM`.
- **Recommended solution:** Query only the target `student_id`'s assignments/results/attempts in SQL (`WHERE student_id = :sid`); rewrite `list_tutor_conversations` using window functions (`DISTINCT ON` / `ROW_NUMBER()`) + grouped `COUNT` (`1–2` SQL queries total); convert sync-DB `async def` routes to `def` (parsing `request.form()` cleanly or via sync helper).
- **Estimated complexity:** Moderate
- **Whether it blocks production deployment:** Fix `async def` -> `def` before launch; SQL query optimizations strongly recommended before or right after launch as exam history accumulates.

### `HIGH-09` — Naive `submission_deadline` Stored Without `Asia/Tehran` Timezone (3.5-Hour Cutoff Shift)
- **Unique finding ID:** `HIGH-09`
- **Severity:** High (Business logic / deadline inaccuracy)
- **Category:** Category 2 — High-priority fix
- **Exact file and relevant function/configuration:** `app/services/exam_service.py` lines 642–643 (naive `submission_deadline`), `app/core/timezone.py` lines 26–50 (`to_local`, `to_utc`, `next_local_midnight_utc`)
- **Evidence from the implementation:** `exam_service.py:642-643` constructs and persists a naive `submission_deadline` datetime without attaching `Asia/Tehran` timezone metadata before writing to PostgreSQL `DateTime(timezone=True)`, while `to_local`/`to_utc` (`timezone.py:29-39`) treat naive datetimes as UTC.
- **Real-world impact:** External exam submission deadlines shift by 3 hours 30 minutes (`Asia/Tehran` UTC+03:30 offset), wrongly marking on-time student submissions as `is_late` or leaving overdue deadlines open late.
- **Whether it actually matters for this project's scale:** Yes — affects all 100 students on every scheduled external exam.
- **Recommended solution:** Build local end-of-day deadline using `get_timezone(DEFAULT_TIMEZONE)` and convert with `to_utc()` (mirroring `next_local_midnight_utc` in `app/core/timezone.py:42-50`).
- **Estimated complexity:** Very easy
- **Whether it blocks production deployment:** Recommended before launch

---

## 7. Easy Fixes (Category 3)

*(Only findings not already listed in Categories 1–2 appear here to avoid double-counting. See Section 15 for total Easy/Moderate/Hard counts across all actionable categories.)*

### `EASY-01` — Dependency Pin Drift Between `pyproject.toml` and `requirements.txt`
- **Unique finding ID:** `EASY-01`
- **Severity:** Low
- **Category:** Category 3 — Easy fix
- **Exact file and relevant function/configuration:** `pyproject.toml` line 12, `requirements.txt` line 1, `Dockerfile` lines 12–13
- **Evidence from the implementation:** `pyproject.toml:12` pins `fastapi==0.162.7`, whereas `requirements.txt:1` (used by `Dockerfile:12-13`) pins `fastapi==0.163.2`.
- **Real-world impact:** Local editable installs test a different FastAPI patch version than the production container.
- **Whether it actually matters for this project's scale:** Minor hygiene issue; easy to prevent environment drift.
- **Recommended solution:** Update `pyproject.toml:12` to `fastapi==0.163.2` so manifests match identically.
- **Estimated complexity:** Very easy
- **Whether it blocks production deployment:** No

### `EASY-02` — Missing Foreign-Key Indexes & Constraint Drift Flagged by `alembic check`
- **Unique finding ID:** `EASY-02`
- **Severity:** Medium
- **Category:** Category 3 — Easy fix
- **Exact file and relevant function/configuration:** `app/models/plan.py` (`PlanAssignment.book_id`, `PlanAssignment.course_id`), `app/models/exam.py` (`ExamReportingGroup.exam_session_id`), `alembic/versions/7b3e21a8d055_stage_3_academic_curriculum.py` lines 26–28, 38–40
- **Evidence from the implementation:** Running `alembic check` against a freshly migrated head database failed (`exit 1`), reporting missing indexes `ix_exam_reporting_groups_exam_session_id`, `ix_plan_assignments_book_id`, `ix_plan_assignments_course_id`, plus redundant unique constraint vs. `unique=True` index declarations on `subjects` and `academic_tracks`.
- **Real-world impact:** Unindexed FKs slightly slow filtered lookups on plan assignments by resource and exam reporting groups by session, and break automated `alembic check` CI gates.
- **Whether it actually matters for this project's scale:** Low latency impact at 100 students today, worthwhile schema cleanliness fix.
- **Recommended solution:** Add one Alembic migration creating the 3 missing indexes and aligning the unique constraint/index metadata.
- **Estimated complexity:** Easy
- **Whether it blocks production deployment:** No

### `EASY-03` — Offline Alembic SQL Generation Crash & Legacy SQLAlchemy 1.x `Query.get()` Calls
- **Unique finding ID:** `EASY-03`
- **Severity:** Low
- **Category:** Category 3 — Easy fix
- **Exact file and relevant function/configuration:**
  - `alembic/versions/0a1b2c3d4e5f_study_plan_assignment_composite_constraints.py` lines 22–55
  - `alembic/versions/1b2c3d4e5f6a_unique_published_study_plan_per_student.py` lines 22–28
  - `app/services/exam_service.py` lines 1379, 1465, 1669
- **Evidence from the implementation:** `alembic upgrade head --sql` failed (`exit 1`) at `0a1b2c3d4e5f:27` with `AttributeError: 'NoneType' object has no attribute 'fetchall'` because `bind.execute(...)` returns `None` in Alembic offline mode; pytest emitted `LegacyAPIWarning` warnings on `db.query(...).get(...)` in `exam_service.py`.
- **Real-world impact:** Blocks offline DBA SQL inspection (`--sql`) and risks breakage on future SQLAlchemy upgrades.
- **Whether it actually matters for this project's scale:** Small maintainability/ops issue at any scale.
- **Recommended solution:** Guard live SQL checks in migrations with `if not context.is_offline_mode():` and replace `db.query(Model).get(...)` with `db.get(Model, ...)`.
- **Estimated complexity:** Easy
- **Whether it blocks production deployment:** No

### `EASY-04` — 46 Demo Seed PDFs Copied into Production Docker Image & Fresh `uploads_data` Volume
- **Unique finding ID:** `EASY-04`
- **Severity:** Low / Medium (operational hygiene)
- **Category:** Category 3 — Easy fix
- **Exact file and relevant function/configuration:** `.dockerignore` lines 27–30, `Dockerfile` line 20 (`COPY --chown=appuser:appuser . .`), `docker-compose.yml` lines 55–56 (`uploads_data:/app/uploads`)
- **Evidence from the implementation:** `git ls-files uploads/` tracks demo PDFs (`~3.68 MB` total across repo static/upload/backup files), and `.dockerignore` excludes only `uploads/**/*.tmp` — so `COPY . .` copies all demo booklets and report cards into `/app/uploads`, which Docker automatically seeds into a newly created `uploads_data` named volume on first boot.
- **Real-world impact:** Pollutes fresh production student storage and backups with demo test PDFs.
- **Whether it actually matters for this project's scale:** Yes for keeping real production student records clean from day one.
- **Recommended solution:** Exclude `uploads/practice_booklets/*`, `uploads/report_cards/*`, `scripts/demo_*.py`, and `*PROGRESS.md` in `.dockerignore` (keeping folder structure created at `Dockerfile:17`).
- **Estimated complexity:** Very easy
- **Whether it blocks production deployment:** No *(clean to apply right before first prod build)*

### `EASY-05` — Missing Login CSRF Token, Hardcoded `secure=True` Cookie Flag, and Never-Pruned `user_sessions` Table
- **Unique finding ID:** `EASY-05`
- **Severity:** Low / Medium
- **Category:** Category 3 — Easy fix
- **Exact file and relevant function/configuration:** `app/routers/auth.py` lines 39, 77–85, 102–108, `app/templates/auth/login.html` line 20, `app/services/auth_service.py` lines 37–116
- **Evidence from the implementation:** `/auth/login` POST lacks CSRF validation; `resp.set_cookie(..., secure=True)` is hardcoded regardless of `ENVIRONMENT`; no code deletes expired or revoked rows from `user_sessions`.
- **Real-world impact:** Minor login-CSRF exposure (low severity without self-signup), broken HTTP login in local non-localhost dev tests, and slow unbounded accumulation of stale `user_sessions` rows.
- **Whether it actually matters for this project's scale:** Small hygiene & dev parity issue (~2,600 expired sessions/year at 100 users, harmless short-term).
- **Recommended solution:** Set `secure = (settings.ENVIRONMENT.lower() == "production")`, add a login CSRF check, and prune `expires_at < now_utc()` rows periodically.
- **Estimated complexity:** Easy
- **Whether it blocks production deployment:** No

### `EASY-06` — Overly Permissive `--forwarded-allow-ips=*` & Unhardened Nginx Server Tokens
- **Unique finding ID:** `EASY-06`
- **Severity:** Low
- **Category:** Category 3 — Easy fix
- **Exact file and relevant function/configuration:** `Dockerfile` line 34 (`CMD`), `nginx/valhalla.conf` lines 26–88
- **Evidence from the implementation:** `Dockerfile:34` runs `uvicorn ... --proxy-headers --forwarded-allow-ips=*`, accepting `X-Forwarded-*` headers from any source IP instead of restricting to `TRUSTED_PROXIES`; `nginx/valhalla.conf` omits `server_tokens off;` and retains `your-domain.com`.
- **Real-world impact:** Currently mitigated by `127.0.0.1:18000` loopback bind, but breaks defense-in-depth if container port exposure changes later.
- **Whether it actually matters for this project's scale:** Low risk on single VPS; trivial hardening.
- **Recommended solution:** Set `--forwarded-allow-ips=127.0.0.1,172.16.0.0/12` in `Dockerfile` / entrypoint and add `server_tokens off;` in `nginx/valhalla.conf`.
- **Estimated complexity:** Very easy
- **Whether it blocks production deployment:** No

### `EASY-07` — Missing Input `max_length` Bounds & Unhandled Duplicate Creation `IntegrityError` Races
- **Unique finding ID:** `EASY-07`
- **Severity:** Medium
- **Category:** Category 3 — Easy fix
- **Exact file and relevant function/configuration:** `app/services/user_service.py` lines 52–72 (`create_student`), `app/services/message_service.py` lines 59–70 (`get_or_create_conversation`), curriculum/plan form handlers
- **Evidence from the implementation:** Columns such as `User.username` (`String(50)`), `User.full_name` (`String(100)`), and `Subject.name` (`String(100)`) are checked in SQLite tests (which do not enforce `VARCHAR(N)` length) without length validation in forms/services; `create_student` checks uniqueness before insert without catching `IntegrityError` under concurrent requests.
- **Real-world impact:** Long strings that succeed under SQLite raise PostgreSQL `StringDataRightTruncation` HTTP 500s in production; double-submitted student/conversation creation returns 500.
- **Whether it actually matters for this project's scale:** Minor real-world edge case affecting PostgreSQL runtime parity.
- **Recommended solution:** Add length validation + HTML `maxlength` matching DB column lengths and catch `IntegrityError` around unique inserts cleanly.
- **Estimated complexity:** Easy
- **Whether it blocks production deployment:** No

### `EASY-08` — Unverified `TestClient` (`117`) & PostgreSQL (`6`) Tests + Missing `pip-audit` Vulnerability Check
- **Unique finding ID:** `EASY-08`
- **Severity:** Medium (Verification gap)
- **Category:** Category 3 — Easy fix
- **Exact file and relevant function/configuration:** `tests/` (`38` files, `228` collected tests), `requirements.txt`
- **Evidence from the implementation:** Only `19` unit/SQLite test files (`105` tests) executed in this Windows sandbox; `17` `TestClient` files (`117` tests) hung at `TestClient(app)`, `test_postgres_integration.py` (`5` tests) skipped without live DB, `test_demo_generator.py` (`1` test) failed on unreachable `localhost:15432`, and no `pip-audit` scan ran.
- **Real-world impact:** HTTP route templates, middleware headers, CSRF middleware behavior, and PostgreSQL row-lock integration tests remain unverified at runtime, alongside dependency CVE posture.
- **Whether it actually matters for this project's scale:** Yes — must verify before launch even for 100 users.
- **Recommended solution:** Run the full `228`-test suite inside the Linux Docker Compose dev stack (`docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm web pytest`) plus `pip-audit` prior to go-live.
- **Estimated complexity:** Easy
- **Whether it blocks production deployment:** No *(code fix is unnecessary if clean; running the full test + CVE check is mandatory verification before launch)*

### `EASY-09` — Redundant `15s` Unread-Badge HTMX Pollers & Missing `load` Trigger on Returned Fragments
- **Unique finding ID:** `EASY-09`
- **Severity:** Low / Medium
- **Category:** Category 3 — Easy fix
- **Exact file and relevant function/configuration:** `app/templates/base.html` lines 161, 236, 312, `app/templates/partials/mobile_nav_drawer.html` lines 47, 114, `app/routers/tutor_messages.py` lines 268, 273, `app/routers/student_chat.py` lines 175, 180
- **Evidence from the implementation:** Every rendered page mounts **3 separate** `hx-trigger="load, every 15s"` unread-badge spans across desktop nav, mobile top bar, and mobile drawer (executing 3 identical DB queries per page every 15 seconds even when elements are `hidden`), and returned HTML fragments overwrite all of them with identical DOM IDs `#student-unread-badge` / `#tutor-unread-badge`.
- **Real-world impact:** Multiplies idle polling DB/worker traffic 3x per connected browser tab and introduces duplicate DOM element IDs.
- **Whether it actually matters for this project's scale:** Noticeable on a 2-core / 2-worker VPS if 40–50 students leave browser tabs open.
- **Recommended solution:** Poll once per tab (adding `[document.visibilityState === 'visible']`) and update badge counts cleanly without duplicating polling triggers on hidden mobile/drawer elements.
- **Estimated complexity:** Easy
- **Whether it blocks production deployment:** No

---

## 8. Moderate Improvements (Category 4)

### `MOD-01` — Self-Service Password Change Flow & Minimum Password Strength Enforcement
- **Unique finding ID:** `MOD-01`
- **Severity:** Medium
- **Category:** Category 4 — Moderate improvement
- **Exact file and relevant function/configuration:** `app/routers/auth.py`, `app/services/user_service.py` lines 37–101 (`create_student`, `reset_student_password`), `app/services/tutor_provision.py`
- **Evidence from the implementation:** Users have no authenticated "Change Password" page/endpoint (`get/post`), and neither `create_student` nor `provision_tutor` validates minimum password length (`len >= 8`). Tutors must run CLI commands to update their own password (currently blocked by `CRIT-03`).
- **Real-world impact:** Students retain tutor-issued initial passwords indefinitely and tutors cannot rotate compromised credentials from the browser.
- **Whether it actually matters for this project's scale:** Yes for ongoing account hygiene (note: full email-token "Forgot Password" SMTP infrastructure is unnecessary when 2–3 tutors manually reset passwords for <=100 known students!).
- **Recommended solution:** Enforce minimum length (`>= 8` chars) in `user_service` & `tutor_provision` immediately, and add `/auth/change-password` in Phase B (requiring current password + revoking other sessions via `revoke_all_user_sessions`).
- **Estimated complexity:** Moderate
- **Whether it blocks production deployment:** No (safely defer UI endpoint to Phase B once `CRIT-03` CLI is fixed; enforce min length quickly).

### `MOD-02` — HTML Error Pages (`401` -> `/auth/login`, `403`, `404`, `500`) & Consistent HTMX Feedback
- **Unique finding ID:** `MOD-02`
- **Severity:** Medium
- **Category:** Category 4 — Moderate improvement
- **Exact file and relevant function/configuration:** `app/main.py` lines 42–53 (`localized_http_exception_handler`), `app/core/dependencies.py` lines 19–30, 51–68
- **Evidence from the implementation:** `localized_http_exception_handler` always returns `JSONResponse` even when a student or tutor clicks a normal browser link with an expired session (`401`) or bad URL (`404`/`403`), and unhandled server exceptions fall back to Starlette's plain `Internal Server Error` response.
- **Real-world impact:** Users whose 14-day session expired see raw JSON `{"detail": "Inactive or invalid session"}` instead of a redirect back to `/auth/login`.
- **Whether it actually matters for this project's scale:** Improves daily student/tutor usability substantially, does not risk data loss.
- **Recommended solution:** For browser HTML requests (non-API/non-JSON `Accept`), redirect `401` cleanly to `/auth/login` (and `HX-Redirect: /auth/login` for HTMX), and render localized `403`/`404`/`500` Jinja error templates.
- **Estimated complexity:** Moderate
- **Whether it blocks production deployment:** No (Phase B — `401` browser redirect is worth prioritizing right after launch).

### `MOD-03` — Scheduler Draft/Status Guards, Time Parsing Validation, and Assignment `display_order` Race
- **Unique finding ID:** `MOD-03`
- **Severity:** Medium
- **Category:** Category 4 — Moderate improvement
- **Exact file and relevant function/configuration:** `app/services/scheduler_service.py` lines 552–553 (`quick_move_meeting`), `update_proposal_item`, `regenerate_unadjusted_items`; `app/services/plan_service.py` (`create_assignment` `display_order`)
- **Evidence from the implementation:** `quick_move_meeting` parses `target_time_str.split(":")` without range validation (risking unhandled `ValueError`/`IndexError` if non-`HH:MM` text arrives); proposal item edit/regenerate routines lack strict `DRAFT` status enforcement on finalized proposals; concurrent `create_assignment` calls can assign duplicate `display_order` values within the same day/subject cell, making up/down swap order non-deterministic.
- **Real-world impact:** Occasional confusing scheduler errors or unreorderable plan cards when two actions happen quickly.
- **Whether it actually matters for this project's scale:** Low-to-moderate impact for 2–3 tutors.
- **Recommended solution:** Validate `time.fromisoformat` / strict `HH:MM` regex, reject mutations on non-`DRAFT` proposals, and serialize `create_assignment` display order under the study plan row lock (`_lock_plan_row` already used elsewhere in `plan_service.py`).
- **Estimated complexity:** Moderate
- **Whether it blocks production deployment:** No (Phase B).

### `MOD-04` — Structured Security/Error Logging & Uploaded File Garbage Collection
- **Unique finding ID:** `MOD-04`
- **Severity:** Medium
- **Category:** Category 4 — Moderate improvement
- **Exact file and relevant function/configuration:** `app/main.py`, `app/routers/health.py:9` (only module creating a `logger`), `app/services/*`, `app/routers/student_exams.py`
- **Evidence from the implementation:** Apart from `health.py`, services and auth/upload routers do not log authentication lockouts, failed file validations, unhandled exceptions, or deleted/replaced report cards; deleting/replacing booklets or report cards can leave orphaned files inside `uploads_data`.
- **Real-world impact:** Hard to diagnose user-reported issues or brute-force attempts from `docker compose logs`; minor gradual disk accumulation from replaced files (mitigated at <=100 students).
- **Whether it actually matters for this project's scale:** Useful operational hygiene (Phase B); Docker `json-file` log rotation (`10m` x `3` per container = 60 MB ceiling) already protects host disk from log exhaustion.
- **Recommended solution:** Add Python `logging` events for failed logins, rate-limit triggers, 5xx errors, and unlink replaced/deleted disk files after DB commit succeeds.
- **Estimated complexity:** Moderate
- **Whether it blocks production deployment:** No (Phase B).

### `MOD-05` — Retire Whole-HTML Regex Persian Localization (`i18n.py`) in Favor of Direct Template Keys
- **Unique finding ID:** `MOD-05`
- **Severity:** Medium
- **Category:** Category 4 — Moderate improvement
- **Exact file and relevant function/configuration:** `app/core/i18n.py` lines 625–696 (`localize_html_content`), `app/core/templates.py` lines 49–65, router snippets (`tutor.py:397`, `student.py:380`, `tutor_messages.py:245`, `student_chat.py:152`)
- **Evidence from the implementation:** Beyond the critical XSS flaw (`CRIT-05`, fixed easily via random nonce), `ValhallaTemplates.TemplateResponse` scans and regex-rewrites entire rendered HTML strings on every Persian response while catching all exceptions silently (`except Exception: pass`), compensating for hardcoded English strings in several router responses.
- **Real-world impact:** Burns unnecessary CPU on large 14-day study plan / analytics pages under `fa` locale and makes translation coverage fragile whenever UI text changes.
- **Whether it actually matters for this project's scale:** Worth cleaning up in Phase B after fixing `CRIT-05` immediately.
- **Recommended solution:** Translate remaining inline router HTML snippets via `translate(..., locale)` at the source (`get_locale_from_request(request)`), move `confirm(...)` strings into `{{ _('...') }}`, and phase out full-HTML regex rewriting.
- **Estimated complexity:** Moderate
- **Whether it blocks production deployment:** No (once `CRIT-05` nonce fix is in place).

---

## 9. Hard / Expensive Problems (Category 5)

### `HARD-01` — Replacing Periodic HTMX Polling with Real-Time WebSockets / SSE Across Multiple Workers
- **Unique finding ID:** `HARD-01`
- **Severity:** Low (at target scale)
- **Category:** Category 5 — Hard / expensive problem
- **Exact file and relevant function/configuration:** `app/templates/base.html:161,236,312`, `app/templates/student/chat.html:58`, `app/templates/tutor/messages/inbox.html:39`, `app/templates/tutor/messages/partials/conversation_pane.html:61`
- **Evidence from the implementation:** Live updates currently rely on HTMX polling (`every 4s` inside open chat threads, `every 15s` on unread badges/inbox, `every 30s` on reminders).
- **What makes it difficult:** True server push across `WEB_CONCURRENCY=2` Uvicorn processes requires cross-worker event fan-out (Redis pub/sub or PostgreSQL `LISTEN/NOTIFY` loops), connection tracking, Nginx WebSocket timeouts, and reconnect resync logic.
- **Real-world impact & scale relevance:** **Does NOT genuinely affect 2–3 tutors and 100 students** once duplicate navbar pollers (`HIGH-06`, `EASY-09`) and `list_tutor_conversations` `2N+1` queries (`HIGH-08`) are fixed. Even 50 simultaneous students polling one indexed unread check every 15–30s produces only ~2–3 trivial SQL queries/sec.
- **Simpler workaround & pre-launch decision:** Keep HTMX polling, consolidate to 1 navbar badge poller per page, and add `[document.visibilityState === 'visible']` to `hx-trigger` so background tabs pause polling. **Do NOT address before launch.**
- **Estimated complexity:** Hard
- **Whether it blocks production deployment:** No

### `HARD-02` — Migrating Synchronous SQLAlchemy ORM (`psycopg2`) & Jinja2 Templates to Full `AsyncSession` (`asyncpg`)
- **Unique finding ID:** `HARD-02`
- **Severity:** Low (at target scale)
- **Category:** Category 5 — Hard / expensive problem
- **Exact file and relevant function/configuration:** `app/core/database.py`, all 11 files in `app/services/` (including `exam_service.py` at 3,079 lines and `plan_service.py` at 1,110 lines), all 18 files in `app/routers/`
- **Evidence from the implementation:** Every service layer uses synchronous SQLAlchemy `Session`, `db.query(...)`, and synchronous lazy-loaded attributes inside Jinja2 templates.
- **What makes it difficult:** Converting to `AsyncSession` requires rewriting thousands of lines of ORM calls, eliminating all lazy attribute loads inside templates (`MissingGreenlet` crashes), refactoring transactional locking, and re-testing all 228+ test cases.
- **Real-world impact & scale relevance:** **Unnecessary at 100 students / 2–3 tutors.** Standard FastAPI synchronous endpoints (`def`, NOT `async def`) run on AnyIO's worker threadpool (40 threads/worker x 2 workers = 80 concurrent blocking handlers), easily serving 50+ simultaneous students.
- **Simpler workaround & pre-launch decision:** Simply convert the ~8 blocking `async def` handlers (`HIGH-04`, `HIGH-08`) to standard `def` (plus fixing full-table exam queries in SQL). **Do NOT rewrite to `AsyncSession`.**
- **Estimated complexity:** Very hard
- **Whether it blocks production deployment:** No

### `HARD-03` — Multi-Tenant SaaS Isolation Between Unrelated Independent Tutors
- **Unique finding ID:** `HARD-03`
- **Severity:** Medium (only if tutors are completely separate businesses)
- **Category:** Category 5 — Hard / expensive problem
- **Exact file and relevant function/configuration:** `app/models/subject.py:35-38` (`Subject.name` globally unique), `app/models/track.py:35-38` (`AcademicTrack.name` globally unique), `app/models/user.py` (no `tenant_id`/`tutor_id` FK on students), `app/models/exam.py`, `app/models/practice_exam.py`, `app/models/book.py`, `app/models/course.py`
- **Evidence from the implementation:** Curriculum, tracks, books, courses, exams, practice exams, and the student directory are global shared academy tables with unique names across the entire database.
- **What makes it difficult:** Partitioning every resource, student, and unique constraint across unrelated competing tutor businesses requires adding tenant/workspace IDs to 20+ tables, complex data migrations, and per-route tenant scoping.
- **Real-world impact & scale relevance:** Assuming the **2–3 tutors operate together within one tutoring group/team serving up to 100 students**, SaaS multi-tenancy is unnecessary; fixing `CRIT-03` (shared academy model with proper actor attribution) solves 2–3 tutor collaboration cleanly. *(If the 2–3 tutors actually run isolated private businesses that must not see each other's students/resources, deploying 2–3 isolated Docker Compose stacks on separate ports/subdomains—or running on slightly larger RAM—is vastly simpler and safer than rewriting the app!)*
- **Simpler workaround & pre-launch decision:** Support cooperating academy tutors in one instance via `CRIT-03` (or deploy separate containers per independent tenant). **Do NOT refactor into multi-tenant SaaS.**
- **Estimated complexity:** Very hard
- **Whether it blocks production deployment:** No *(handled as team tutors in `CRIT-03`)*

---

## 10. Optional Improvements That Are Not Worth Implementing (Category 6)

For `2–3 tutors` and `<=100 students` on one `2-core / 4 GB VPS`, the following enterprise patterns add operational failure modes and RAM cost without meaningful benefit:

### `OPT-01` — Redis / Valkey Cluster for Sessions, HTML Caching, or Rate Limiting
- **Unique finding ID:** `OPT-01`
- **Severity:** Info / N/A
- **Category:** Category 6 — Optional / unnecessary for this project
- **Exact file and relevant function/configuration:** `app/services/auth_service.py` (`UserSession`), `app/core/rate_limit.py` (`LoginRateLimiter`)
- **Evidence from the implementation:** Authentication already stores SHA-256 `token_hash` sessions in PostgreSQL (`user_sessions`, indexed unique column).
- **Real-world impact:** At <=100 students (~100 active session rows), indexed PostgreSQL lookups take `<1 ms`; adding Redis introduces extra RAM usage inside 4 GB and a third stateful service to monitor/configure.
- **Whether it actually matters for this project's scale:** No — unnecessary below ~1,000+ concurrent requests/sec.
- **Recommended solution:** Keep PostgreSQL-backed sessions (and if cross-worker rate-limit persistence is added in `HIGH-05`, use a lightweight Postgres table + Nginx `POST` throttling instead of Redis).
- **Estimated complexity:** Moderate
- **Whether it blocks production deployment:** No

### `OPT-02` — Celery / RQ / Dramatiq Background Job Workers
- **Unique finding ID:** `OPT-02`
- **Severity:** Info / N/A
- **Category:** Category 6 — Optional / unnecessary for this project
- **Exact file and relevant function/configuration:** `app/services/scheduler_service.py`, `app/core/storage.py`
- **Evidence from the implementation:** All operations are fast synchronous DB mutations (`<=100` students) or direct streaming writes (`<=25 MB` files).
- **Real-world impact:** Running a broker + Python worker process consumes 150–300 MB extra RAM and adds stuck-job operational overhead with no user benefit.
- **Whether it actually matters for this project's scale:** No.
- **Recommended solution:** Keep request-response execution using standard FastAPI `def` threadpool endpoints (`HIGH-04`).
- **Estimated complexity:** Hard
- **Whether it blocks production deployment:** No

### `OPT-03` — Kubernetes, Docker Swarm, or Multi-Node Autoscaling
- **Unique finding ID:** `OPT-03`
- **Severity:** Info / N/A
- **Category:** Category 6 — Optional / unnecessary for this project
- **Exact file and relevant function/configuration:** `docker-compose.yml`, `nginx/valhalla.conf`
- **Evidence from the implementation:** Single-host Docker Compose + host Nginx fits the entire stack in `<2 GB` RAM.
- **Real-world impact:** Orchestration control planes waste RAM and complicate debugging/backups for a 1-administrator VPS.
- **Whether it actually matters for this project's scale:** No.
- **Recommended solution:** Keep single-VPS Docker Compose + Ubuntu host Nginx (`Phase A` right-sized).
- **Estimated complexity:** Very hard
- **Whether it blocks production deployment:** No

### `OPT-04` — S3 / CloudFront Runtime Upload Storage & Presigned URL Proxying
- **Unique finding ID:** `OPT-04`
- **Severity:** Info / N/A
- **Category:** Category 6 — Optional / unnecessary for this project
- **Exact file and relevant function/configuration:** `app/core/storage.py` (`save_uploaded_file`, `get_upload_base_path`), `docker-compose.yml` (`uploads_data`)
- **Evidence from the implementation:** Current `uploads/` assets total `~3.68 MB` across 46 demo files; per-file limits are 10 MB (report cards) and 25 MB (booklets).
- **Real-world impact:** Even over multiple years for 100 students, local SSD volume storage stays within a few GB, whereas rewriting upload/download authorization flows to S3 presigned URLs adds complexity and network dependencies.
- **Whether it actually matters for this project's scale:** No for *runtime* storage (off-VPS *backups* remain mandatory via `CRIT-04`).
- **Recommended solution:** Keep `uploads_data` local with `FileResponse` auth checks and back it up off-VPS nightly (`CRIT-04`).
- **Estimated complexity:** Moderate
- **Whether it blocks production deployment:** No

### `OPT-05` — PostgreSQL Read Replicas, Sharding, or External PgBouncer
- **Unique finding ID:** `OPT-05`
- **Severity:** Info / N/A
- **Category:** Category 6 — Optional / unnecessary for this project
- **Exact file and relevant function/configuration:** `app/core/database.py` (`create_engine`), `docker-compose.yml` (`db`)
- **Evidence from the implementation:** With `WEB_CONCURRENCY=2` and bounded SQLAlchemy pools (`5+5`), maximum DB connections stay at `<=20`.
- **Real-world impact:** Extra database nodes/proxies double failure surfaces without solving any real bottleneck at 100 students.
- **Whether it actually matters for this project's scale:** No.
- **Recommended solution:** Use single-instance PostgreSQL 16 with `HIGH-02` memory/pool settings and `HIGH-08` SQL query filtering.
- **Estimated complexity:** Hard
- **Whether it blocks production deployment:** No

---

## 11. Performance and Concurrency Assessment

**Disclaimer (Honest Verification Boundary):** None of the multi-user concurrency scenarios below have been executed via live load testing in this assessment. Behavior is derived directly from inspecting worker counts, database pooling, query shapes, `with_for_update` locks, blocking I/O patterns, and polling frequency in the codebase.

### Configured Runtime Concurrency Parameters
- **Application workers:** `WEB_CONCURRENCY=2` (`scripts/entrypoint.sh:49`, `.env.example:31`), Uvicorn without `--threads` (single event loop per worker + Starlette/AnyIO default `40` threadpool threads per worker for sync `def` endpoints = `80` total sync handlers across 2 workers).
- **Database engine & pooling:** Sync `psycopg2` via `create_engine(..., pool_pre_ping=True)` (`app/core/database.py:9-13`) -> currently defaults to `pool_size=5, max_overflow=10` per worker (`30` total connections max across 2 workers). Recommend capping at `pool_size=5, max_overflow=5` (`20` max).
- **Nginx:** Host Nginx TLS + gzip level 5 + `client_max_body_size 35M` + `proxy_read_timeout 120s` (`nginx/valhalla.conf`).

### Realistic Concurrency Scenario Analysis

| Scenario | Current Code Estimate | Bottlenecks Triggered & Impact | With Phase A Fixes Applied |
|---|---|---|---|
| **1. 10 students active simultaneously** | Comfortable after `CRIT-01`/`CRIT-02` | ~30 idle badge polls every 15s (`EASY-09`); 1–2 simultaneous uploads to `async def` stall one worker momentarily | Sub-50 ms responses; negligible CPU (`<10%`) & RAM |
| **2. 25 students active simultaneously** | Mostly smooth, occasional hiccups | Simultaneous `/student/exams` loads (`HIGH-08`) scan all DB results per request; simultaneous report card uploads stall `async def` workers (`HIGH-04`) | Easily handled within ~1.2–1.5 GB total VPS RAM and <25% CPU |
| **3. 50 students active simultaneously** | Risky under current code | High chance of `async def` event loop starvation during concurrent report-card/practice-exam submissions, duplicate poll storm (~10 badge queries/sec), and shared Wi-Fi login throttling on `GET /auth/login` (`HIGH-05`) | Well within 2-core / 2-worker capacity (~80 AnyIO sync threads, `<50–60%` burst CPU, assuming Argon2 logins are spread over 1–2 min) |
| **4. Peak period: ~100 registered students within a short window** (e.g., all opening platform right after a mock exam finishes) | Vulnerable without fixes | Argon2id login burst (at ~100ms CPU per login, 2 cores process ~15–20 logins/sec max); combined with `get_student_available_exams` full-table scans (`HIGH-08`) and blocking uploads (`HIGH-04`), latency spikes and `HIGH-05` Nginx `503` hits shared IPs | Smooth queue drain in a few seconds; bounded 20 DB connections; zero 502/503/500 errors if `GET /auth/login` is unthrottled and queries filter by `student_id` |
| **5. 2–3 tutors active while students are active** | **Broken (`CRIT-03`)** & inbox heavy (`HIGH-08`) | Tutors 2–3 hit `MessagePermissionError` / 500s on scheduler & chat; open `/tutor/messages` runs `201` queries every `15s` per tutor; double reminder widget causes concurrent reminder updates (`HIGH-06`) | Smooth parallel work (`1–2` SQL inbox queries, clean multi-tutor access, zero interference with students) |

### Most Useful Pre-Launch Load Tests & Acceptance Criteria
Before launch, run a lightweight **10–15 minute Docker Compose staging smoke test** on a `2-core / 4 GB` VPS (e.g., using `k6` or `locust` with real seeded 100 students, 3 tutors, 20 exams x 100 results = 2,000 result trees):
1. **Login + Dashboard Ramp:** 50 virtual students log in over 60s and load `/student/dashboard`, `/student/plan`, `/student/exams`, `/student/practice-exams`.
   - *Acceptance:* `0%` unexpected `5xx`/`502`/`503` errors; `p95` dashboard/plan `< 400 ms`; `p95` login `< 1,500 ms` under simultaneous Argon2 burst.
2. **Post-Exam Result + Upload Burst:** 25 virtual students simultaneously submit external exam results with 2 MB PDF report cards while 2 tutors browse `/tutor/messages` and `/tutor/calendar`.
   - *Acceptance:* `0%` upload errors or timeouts; `p95` `< 1,500 ms`; container peak RSS `< 768 MB` (`db`) and `< 1,024 MB` (`web`); host swap usage minimal/zero OOM kills.
3. **Practice Exam Timer Race Test:** Automated test submitting booklet on timer expiry (`0s`) verifies saved answers persist 100% (`0` `None` overwrites).

---

## 12. Database and Data Integrity Assessment

### Suitability for 100 Students & 2–3 Tutors
**PostgreSQL 16 is an ideal fit** and should **NOT** be changed or replaced. The relational schema fits cleanly in tens of megabytes for 100 students, supports strict constraints (`TIMESTAMPTZ`, partial unique indexes, `RESTRICT`/`CASCADE` FKs, row locking), and requires zero clustering or read replicas.

### Schema, Constraints, Indexes & Migration Findings
- **Strengths verified in models & migrations:**
  - Explicit naming convention (`POSTGRES_NAMING_CONVENTION` in `app/models/base.py:8-14`).
  - Strong cross-table tenant/entity guarantees: `uq_study_plans_id_student` + composite FK `fk_plan_assignments_study_plan_student` (`0a1b2c3d4e5f`), partial unique index `uq_study_plans_student_published` (`1b2c3d4e5f6a`), `ondelete="RESTRICT"` on `completion_audit_logs.assignment_id` (`2c3d4e5f6a7b`) and `subjects` / `academic_tracks` FKs.
  - Concurrency locking (`with_for_update`) properly implemented in key places (`practice_exam_service` attempt start/answer, `plan_service` assignment completion/delete, `exam_service` review/result edits).
  - Linear 19-revision Alembic history (`9c005c0812c7` -> `2c3d4e5f6a7b`), cleanly upgrading a fresh SQLite DB (`alembic upgrade head`).
- **Verified Gaps:**
  1. `Conversation` unique constraint `uq_conversations_student_id` + single `tutor_id` breaks multi-tutor messaging/scheduler workflows (`CRIT-03`).
  2. `alembic check` exited `1`: missing indexes on `exam_reporting_groups.exam_session_id`, `plan_assignments.book_id`, and `plan_assignments.course_id`, plus model-vs-migration discrepancy for `unique=True` constraints vs indexes on `subjects.name` and `academic_tracks.name` (`EASY-02`).
  3. `alembic upgrade head --sql` crashes on live `bind.execute(...)` checks in `0a1b2c3d4e5f` (and `1b2c3d4e5f6a` uses the same unguarded pattern) (`EASY-03`).
  4. Missing `PracticeExam` FK check before `delete_track` (`HIGH-07`) and duplicate `IntegrityError` handling in `create_student` / `get_or_create_conversation` (`EASY-07`, `HIGH-07`).
  5. Full-table ORM fetches instead of `WHERE student_id = ...` filtering (`HIGH-08`) and `get_due_reminders` lacking row locks (`HIGH-06`).
  6. `user_sessions` never prunes expired/revoked rows (`EASY-05`).
  7. PostgreSQL-specific concurrency tests (`test_postgres_integration.py`, 5 tests) and demo lifecycle (`test_demo_generator.py`, 1 test) **were NOT verified against live PostgreSQL 16** in this sandbox.

---

## 13. Backup and Disaster Recovery Assessment

### Failure Recovery Matrix (Current State)

| Disaster / Failure Scenario | Current Recoverability | Root Gap |
|---|---|---|
| Accidental deletion of student data (e.g., exam, user, DB mistake) | **Unrecoverable** | No automated scheduled `pg_dump` or point-in-time archive (`backups/` empty) |
| Database corruption | **Unrecoverable** | Single local `postgres_data` volume only |
| Failed Alembic migration on deploy | **Downtime + Unrecoverable if destructive** | `AUTO_MIGRATE=true` in `scripts/entrypoint.sh` upgrades schema on startup before any backup is taken, causing restart loops (`unless-stopped`) |
| Full VPS failure / disk loss / provider deletion | **Total permanent loss** | Zero off-VPS backup replication for both DB and `uploads_data` |
| Container failure (`web` / `db` crash) | Recoverable (`postgres_data` & `uploads_data` persist) | Unless `docker compose down -v` is run mistakenly or disk fills |
| Disk exhaustion | Partial risk | Container logs are well-bounded (`10m` x `3` = 60 MB), but `uploads_data` has no host disk alert/quota and backups aren't pruned |
| Unsuccessful code deployment | Rollback fragile | If DB schema changed in failed deploy (`AUTO_MIGRATE=true`), reverting app code leaves forward-migrated DB incompatible |

**Verification Status:** Backups are **NOT automated**, **NOT stored outside the VPS**, **NOT protected from accidental deletion** (local backups sit on the same VPS), and **NEVER tested via actual restore**. An untested backup procedure is not a recovery strategy.

### Recommended Simple Backup & Recovery Strategy (No Enterprise Complexity)
1. **Automated Host Daily Backup Script (`/usr/local/bin/valhalla-backup.sh` via Ubuntu cron/systemd timer at `03:30` `Asia/Tehran`):**
   - Run `docker compose exec -T db pg_dump -U postgres -d valhalla_db -F c -f /var/lib/postgresql/backups/db_$(date +%F_%H%M).dump`
   - Run `docker compose exec -T web tar -czf - -C /app uploads > backups/uploads_$(date +%F_%H%M).tar.gz` (after removing seed demo files per `EASY-04`)
   - Prune local files in `./backups/` older than `7–14` days (`find ... -mtime +14 -delete`).
2. **Off-VPS Protected Copy (`restic` or `rclone`):**
   - Push `./backups/` nightly to an inexpensive S3-compatible bucket (Backblaze B2 / Cloudflare R2 / Hetzner Storage Box / separate VPS) using **append-only / object-lock or non-delete API credentials** so even root compromise on the VPS cannot delete older off-site restore points.
3. **Safe Deployment Script (`AUTO_MIGRATE=false`):**
   - Disable `AUTO_MIGRATE=true` in production `.env`. Every update runs: `(1) take pre-update pg_dump -> (2) docker compose build -> (3) docker compose run --rm --no-deps web alembic upgrade head -> (4) docker compose up -d web -> (5) verify curl http://127.0.0.1:18000/health/db`.
4. **Mandatory Pre-Launch Restore Drill:**
   - Spin up a disposable test project name (`docker compose -p valhalla_restore_test ...`), restore the `.dump` via `pg_restore` and extract `uploads_*.tar.gz`, boot `web`, log in, open an uploaded PDF, and verify row counts match. Repeat quarterly.

---

## 14. Recommended Minimum Production Configuration

Without impacting unrelated services on the same Ubuntu VPS (`127.0.0.1:18000` avoids colliding with ports `8000` or `5432`):

1. **Nginx (`nginx/valhalla.conf`):**
   - Point upstream explicitly to `server 127.0.0.1:18000 fail_timeout=10s max_fails=3;` (`CRIT-01`).
   - Replace `your-domain.com` with actual domain & Certbot cert paths; add `server_tokens off;` (`EASY-06`).
   - Scope `limit_req zone=valhalla_auth` strictly to `POST` on `/auth/login` (`limit_except GET HEAD { ... }` or equivalent Nginx block) so students opening login behind school NAT Wi-Fi aren't rejected (`HIGH-05`).
2. **Docker Compose (`docker-compose.yml`):**
   - Keep `"127.0.0.1:18000:8000"` loopback bind (`web`) and internal-only `valhalla_network` (`db` never published to host).
   - Cap `db` at `limits.memory: 768M` (`cpus: '1.0'`) and configure Postgres flags:
     `command: ["postgres", "-c", "shared_buffers=256MB", "-c", "effective_cache_size=768MB", "-c", "work_mem=4MB", "-c", "max_connections=50"]`.
   - Cap `web` at `limits.memory: 1024M` (`cpus: '1.5'`).
   - Keep `json-file` logging (`max-size: 10m`, `max-file: 3`), `restart: unless-stopped`, healthchecks, and `stop_grace_period: 30s`.
3. **Production `.env`:**
   - `ENVIRONMENT=production`, `DEBUG=False`, `DEFAULT_TIMEZONE=Asia/Tehran`
   - Strong random 32+ char `POSTGRES_PASSWORD` (no `"postgres"` or example placeholder)
   - `AUTO_MIGRATE=false` (paired with backup-first deploy script)
   - `WEB_CONCURRENCY=2`
   - `TRUSTED_PROXIES=127.0.0.1,::1,172.16.0.0/12,10.0.0.0/8` (and align Uvicorn `--forwarded-allow-ips=127.0.0.1,172.16.0.0/12` in `Dockerfile`).
4. **Application Engine & Assets:**
   - Set SQLAlchemy `pool_size=5, max_overflow=5, pool_recycle=1800` in `app/core/database.py` (max 20 DB connections across 2 workers).
   - Vendor Tailwind CSS compiled output + `htmx` + `chart.js` + `Vazirmatn` under `app/static/` (`HIGH-03`) and strip demo PDFs from Docker image (`.dockerignore`, `EASY-04`).
5. **Provisioning & Monitoring:**
   - Run `python -m app.cli seed-academic` and create your 2–3 tutor accounts after fixing `CRIT-03`.
   - Configure a simple external uptime ping against `https://your-domain.com/health/db` (every 1–5 min) plus host disk-space alert (`df -h` `< 20%` free).

---

## 15. Prioritized Action Plan

*(Effort estimated in engineering time for one familiar developer, not calendar dates. Counts cover all `31` actionable findings in Categories 1–5: **19 Easy [7 Very easy + 12 Easy]**, **9 Moderate**, **3 Hard [1 Hard + 2 Very hard]** — plus 5 Category 6 non-goals.)*

### Phase A — Must Fix Before Launch

| Order | Finding(s) | Concrete Task | Est. Engineering Effort |
|---:|---|---|---:|
| 1 | `CRIT-01`, `EASY-06`, `HIGH-02` | Fix Nginx/Compose port (`18000`), set `db: 768M` / `web: 1024M` + Postgres flags + SQLAlchemy pool caps, tighten `--forwarded-allow-ips` & `server_tokens off`, set `AUTO_MIGRATE=false` | `1–2 hours` |
| 2 | `CRIT-02` | Stop disabling `.choice-radio` on timed auto-submit in `runner.html`; protect existing answers on partial/omitted form submit; add timed auto-submit regression test | `2–4 hours` |
| 3 | `CRIT-05` | Replace deterministic `___VALHALLA_PROTECTED_{i}___` placeholder in `app/core/i18n.py` with per-render cryptographic nonce + add XSS regression test in `fa` locale | `1–2 hours` |
| 4 | `CRIT-03` | Fix `provision_tutor` to allow multiple tutors (`2–3`); migrate chat/scheduler/plans to shared-academy multi-tutor support (with `sender_id` / creator attribution) + add multi-tutor tests | `4–8 hours` |
| 5 | `CRIT-04`, `EASY-04` | Exclude demo `uploads/` PDFs from Docker build; install daily automated `pg_dump` + `uploads` backup cron/timer with off-VPS `restic`/`rclone` sync; run one verified restore drill + create safe update script | `3–5 hours` |
| 6 | `HIGH-01`, `HIGH-09` | Add production startup validation rejecting `DEBUG=True` or default `POSTGRES_PASSWORD`; attach `Asia/Tehran` timezone to `submission_deadline` | `1–2 hours` |
| 7 | `HIGH-04`, `HIGH-08` | Validate PDF/image magic bytes in `save_uploaded_file`; convert blocking `async def` upload/DB handlers to `def`; filter `get_student_available_exams` & `get_student_available_practice_exams` by `student_id` in SQL; fix `list_tutor_conversations` `2N+1` | `4–8 hours` |
| 8 | `HIGH-03` | Self-host `htmx`, `chart.js`, `Vazirmatn`, and compiled Tailwind CSS under `app/static/` so UI has zero external CDN runtime dependency and drop `'unsafe-eval'` from CSP | `3–6 hours` |
| 9 | `HIGH-05`, `HIGH-06`, `HIGH-07` | Lowercase login identifier + constant-time unknown-user verify; scope Nginx `limit_req` to `POST /auth/login`; deduplicate navbar reminder widget & add row lock (`SKIP LOCKED`) / `#modal-container`; catch `PracticeExam` FK on track delete & URL-encode error redirects | `3–5 hours` |
| 10 | `EASY-08` | Execute **all `228` tests** (`TestClient` + PostgreSQL 16 integration) inside Linux Docker Compose, run `pip-audit`, and run the Section 11 50-user load smoke test | `2–4 hours` |
| **Total Phase A** | | | **~24–44 eng. hours (3–6 focused days)** |

### Phase B — Should Fix Soon After Launch

| Order | Finding(s) | Concrete Task | Est. Engineering Effort |
|---:|---|---|---:|
| 1 | `EASY-01`, `EASY-02`, `EASY-03` | Sync `pyproject.toml` FastAPI pin; add migration for 3 missing FK indexes + constraint sync; fix `alembic --sql` offline guard & `db.get()` warnings | `2–3 hours` |
| 2 | `EASY-05`, `EASY-07`, `EASY-09` | Add login CSRF protection, dev HTTP cookie flag, and periodic expired `user_sessions` cleanup; validate input max lengths & race `IntegrityError`s; consolidate unread-badge polling with visibility check | `3–4 hours` |
| 3 | `MOD-01`, `MOD-02` | Enforce `>= 8` char password minimum + build authenticated `/auth/change-password`; redirect browser `401` HTML requests to `/auth/login` + add HTML `403`/`404`/`500` error pages | `4–6 hours` |
| 4 | `MOD-03`, `MOD-04`, `MOD-05` | Add scheduler proposal state/time bounds + `display_order` lock; add structured auth/5xx logging & upload deletion cleanup; gradually replace whole-HTML `fa` regex rewriting with direct template translation keys | `6–10 hours` |
| **Total Phase B** | | | **~15–23 eng. hours (2–3 days)** |

### Phase C — Future Improvements (Only If Growth Exceeds Current Scale)

- Split `exam_service.py` (3,079 lines) and `plan_service.py` (1,110 lines) into focused sub-modules if feature velocity increases significantly.
- Consider WebSockets/SSE (`HARD-01`), async ORM (`HARD-02`), or multi-tenant workspace separation (`HARD-03`) **only** if migrating beyond ~500+ active students or separate external tutor organizations.

---

### Direct Answer to Operator Question

> *"If this were your own application, serving 2–3 tutors and 100 students on a 2-core / 4 GB VPS, what exactly would you fix before allowing real students to use it, and what would you deliberately leave alone?"*

**Exactly what I would fix BEFORE letting real students log in:**
1. Fix the `docker-compose.yml` (`18000`) / `nginx/valhalla.conf` (`8000`) port bug (`CRIT-01`) and lower container memory limits to `768M` DB + `1024M` Web with tuned Postgres/pool settings (`HIGH-02`).
2. Fix the timed practice exam auto-submit bug so `.choice-radio` inputs aren't disabled before submit and missing form fields never wipe auto-saved answers (`CRIT-02`).
3. Fix the random nonce in `app/core/i18n.py` placeholder substitution to eliminate `fa` XSS (`CRIT-05`), validate upload magic bytes (`HIGH-04`), and fail startup if `DEBUG=True` or default DB password is used in `production` (`HIGH-01`).
4. Fix `provision_tutor`, multi-tutor chat/scheduler (`MessagePermissionError` / `uq_conversations_student_id`), and study plan tutor visibility (`CRIT-03`), plus naive exam `submission_deadline` timezone handling (`HIGH-09`) and `async def` -> `def` conversion + SQL filtering on student exam/inbox queries (`HIGH-04`, `HIGH-08`).
5. Bundle `htmx`, `chart.js`, `Vazirmatn`, and compiled Tailwind CSS locally in `app/static/` (`HIGH-03`) so student pages don't break on CDN hiccups, fix case-insensitive login + Nginx `POST`-only rate-limit + reminder widget duplication (`HIGH-05`, `HIGH-06`, `HIGH-07`).
6. Set up automated daily `pg_dump` + `uploads` backups copied off-VPS (`restic`/`rclone`), disable `AUTO_MIGRATE=true`, perform **one actual test restore**, and run all `228` pytests inside Docker + `pip-audit` (`CRIT-04`, `EASY-04`, `EASY-08`).

**What I would DELIBERATELY leave alone:**
- Keep PostgreSQL 16 (`db`), FastAPI/Jinja2/HTMX monolith (`web`), and host Nginx on the single `2-core / 4 GB` VPS — do **not** add Redis (`OPT-01`), Celery (`OPT-02`), Kubernetes (`OPT-03`), S3 runtime media storage (`OPT-04`), or PgBouncer/replicas (`OPT-05`).
- Do **not** rewrite synchronous SQLAlchemy services to `AsyncSession` (`HARD-02`) — changing blocking `async def` routes to `def` + fixing the 3 N+1/full-table SQL queries is 20x cheaper and equally fast at 100 students.
- Do **not** build WebSockets/SSE (`HARD-01`) — visibility-aware HTMX polling (`1` navbar poller) works reliably for 2–3 tutors and 100 students.
- Do **not** build email SMTP password-reset flows (`MOD-01` partial) or SaaS multi-tenancy (`HARD-03`) if tutors work on one team and handle student resets manually.

---

## 16. Final Recommendation

1. **Hold production launch** until **Phase A** (`CRIT-01`–`CRIT-05` plus the targeted `HIGH-*` operational fixes and full Linux/Docker test verification) is completed and verified via a real restore drill.
2. **Maintain the current architecture** (PostgreSQL 16 + FastAPI sync endpoints + Jinja2 + HTMX + Docker Compose + host Nginx) — it is clean, appropriate, maintainable by 1 administrator supporting 2–3 tutors, and will run comfortably on a **2 CPU core / 4 GB RAM VPS** for up to 100 students once resource limits and N+1/blocking endpoints are corrected.
3. **Schedule Phase B** during the first 1–2 weeks post-launch to complete observability logging, HTML 401/403/500 pages, self-service password change, missing DB indexes, and regex-i18n cleanup.
