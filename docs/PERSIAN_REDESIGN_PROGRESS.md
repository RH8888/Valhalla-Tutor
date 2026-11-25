# Persian (Farsi) Experience Redesign — Progress Tracker

## Current Implementation Decisions
1. **Direction System**: Centralized HTML `dir="rtl" lang="fa"` / `dir="ltr" lang="en"` in `base.html`, paired with CSS logical properties (`ms-`, `me-`, `ps-`, `pe-`, `start-`, `end-`, `text-start`, `border-s`, `border-e`, `rounded-s`, `rounded-e`, `gap-*`) and a dedicated `app/static/css/persian-ui.css` stylesheet. Zero scattered CSS hacks.
2. **Typography**: Vazirmatn font (weights 400–900) for Persian, with explicit `letter-spacing: 0` in RTL (preventing broken cursive joins from Tailwind `tracking-*` classes), tailored line-heights (`1.75` body / `1.4` headings), and `tabular-nums` for numbers/tables.
3. **Mixed-Direction Isolation**: `.bidi-ltr` / `dir="ltr"` with `unicode-bidi: isolate` for usernames, email addresses, URLs, codes, and technical IDs.
4. **Calendar & Locale Formatting**: Jalali (Shamsi) calendar dates, Persian month & weekday names, Persian digits (`۰-۹`), percentages, durations, and currency formatting via centralized helpers in `app/core/i18n.py` and Jinja filters, without altering DB storage or API contracts.
5. **Language Persistence**: `valhalla_locale` cookie (`max_age=31536000`, `path=/`, `samesite="lax"`), preserved across refresh, login, and logout; query strings preserved on `/set-language` redirects; sensible default (`en`) for new users.

## Completed Phases
- Phase 0: Architecture Audit & Planning (completed)
- Phase 1: Core i18n, Direction, Typography & Locale Formatting Architecture (completed & verified)
- Phase 2: Complete Locale Catalog & Backend Router/Service Messages Audit (completed & verified)
- Phase 3: Student Experience Templates, JS, & Charts Overhaul (completed & verified)
- Phase 4: Tutor Students, Messages, Calendar & Scheduler Overhaul (completed & verified)
- Phase 5: Tutor Plans, Curriculum & Assessments Overhaul (completed & verified: Phase 5A 5/5, Phase 5B 7/7, Phase 5C 31/31)
- Phase 6: Comprehensive Pytest & Live Browser Testing (completed & verified: 49-route HTML audit clean, `tests/test_persian_redesign.py` 6/6 passed, headless Chrome desktop `1280px` & mobile `320/360/375/390/414/430px` passed with zero horizontal overflow, full suite `191 passed, 2 pre-existing baseline failures`)

## Files Modified
- `docs/PERSIAN_REDESIGN_PROGRESS.md`
- `app/core/i18n.py`, `app/core/templates.py`, `app/main.py`, `app/routers/tutor_calendar.py`, `app/routers/tutor_plans.py`
- `app/static/css/persian-ui.css`, `app/static/js/i18n.js`
- `app/locales/en.json`, `app/locales/fa.json` (total 2,207 keys, zero missing template keys)
- `app/templates/base.html`, `partials/mobile_nav_drawer.html`, `auth/login.html`, `partials/*_tabs.html`, `messaging/message_bubble.html`
- All 15 student templates & partials
- All tutor students, monitoring, messaging, calendar, and scheduler templates (`tutor/students/*`, `tutor/messages/*`, `tutor/calendar/*`, `tutor/scheduler/*`)
- All tutor plans, planner, tracks, subjects, videos, books, exams, practice_exams, and historical_exams templates (`tutor/plans/*`, `tutor/tracks/*`, `tutor/subjects/*`, `tutor/videos/*`, `tutor/books/*`, `tutor/exams/*`, `tutor/practice_exams/*`, `tutor/historical_exams/*`)
- `tests/test_persian_redesign.py`

## Remaining Tasks
- None (all phases complete and verified)

## Known Issues / Baseline Limitations
- Two pre-existing baseline test failures unrelated to this work (`pytest -k "not postgres"`):
  - `tests/test_auth_routes.py::test_logout`: fails with 403 because the pre-existing test omits `csrf_token` on `POST /auth/logout`.
  - `tests/test_demo_generator.py::test_demo_generator_and_cleanup_lifecycle`: requires a PostgreSQL instance running on `localhost:15432` (`valhalla_db`).
- Two `tests/test_postgres_integration.py` tests deselected via `-k "not postgres"` because PostgreSQL was not running locally during test execution.
