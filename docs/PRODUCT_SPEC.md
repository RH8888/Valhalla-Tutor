# Product Specification: Academic Planner

## 1. Product Overview
Valhalla Tutor Academic Planner is a lightweight, self-hosted academic planning web application built for a single tutor managing approximately 100 students.

The platform provides a structured, distraction-free environment for:
- Managing a hierarchical curriculum (Subjects -> Books -> Chapters -> Test counts).
- Generating and distributing structured individual two-week (14-day) study plans.
- Assigning specific chapter test ranges across plan dates.
- Tracking student assignment completion and deadline compliance in real time.
- Logging external examination results without global competitive rankings.

### Explicit Non-Goals
To keep the application focused, robust, and lightweight, the following are strictly out of scope:
- School Management System (SMS) or Learning Management System (LMS) features.
- In-app test content, online quizzes, answer submissions, or automated grading.
- Tutoring CRM, invoicing, billing, or payroll.
- Global student leaderboards, public ranking comparisons, or social gamification.
- Multi-tenant tutor SaaS capabilities (strictly single-tutor operation).

## 2. User Roles & Capabilities

### 2.1 Tutor
- **Authentication**: Secure login via username/email and password.
- **Student Management**: Create student accounts, set temporary passwords, activate/deactivate accounts.
- **Curriculum Management**: Create, update, reorder, and archive Subjects, Books, and Chapters with available test counts.
- **Study Plan Creation**: Build individual study plans for specific students (standard length: 14 calendar days). Set draft/published status.
- **Assignment Scheduling**: Assign test intervals (`start_test_num` to `end_test_num`) from specific chapters to calendar dates within a plan.
- **Progress Monitoring**: View completion rates across students, inspect overdue/pending assignments, identify students falling behind.
- **Exam Oversight**: Review external examination records recorded by students.

### 2.2 Student
- **Authentication**: Secure login via credentials assigned by the tutor.
- **Study Plan Access**: View current published 14-day study plan and browse past archived plans.
- **Daily Work Schedule**: View assignments grouped by scheduled date and status.
- **Assignment Completion**: Mark scheduled assignments as completed with a single toggle/button action.
- **Deadlines & Statuses**: Clear indicators of upcoming deadlines and overdue items.
- **External Exams**: Create and manage individual external examination records.

## 3. Core Functional Requirements

### 3.1 Curriculum Hierarchy
- **Subject**: E.g., Mathematics, Physics, Chemistry.
- **Book**: Associated with one subject. E.g., "Halliday & Resnick Physics Vol 1".
- **Chapter**: Belongs to one book. Contains title, chapter number/order, and `total_tests` (positive integer indicating how many tests/exercises exist).

### 3.2 Study Plans
- An individual study plan is assigned to exactly one student.
- Scope: Exactly 14 consecutive calendar days (`end_date = start_date + 13 days`, inclusive).
- Statuses:
  - `DRAFT`: Visible only to the tutor.
  - `PUBLISHED`: Visible to the assigned student and tutor. Active for work. Enforced at most one `PUBLISHED` study plan per student at any given time via a database-level partial unique index.
  - `ARCHIVED`: Past plan retained for historical review.
- All assignments within a plan must strictly fall within `[start_date, end_date]`.
- Tutor creates, edits, and publishes plans. Once published, assignments remain locked against accidental student tampering.

### 3.3 Assignments
- An assignment belongs to a specific `StudyPlan` and `Student` (strictly constrained via composite keys so an assignment cannot reference a student different from the plan owner).
- Tied directly to a curriculum node: `Subject`, `Book`, and `Chapter`. Database foreign keys enforce relational consistency (book must belong to subject, chapter must belong to book).
- Specifies an inclusive test range: `start_test_num` and `end_test_num` where `1 <= start <= end <= chapter.total_tests`.
- Attributes:
  - `scheduled_date` (Date): The day the student is expected to work on this assignment (must fall within the 14-day study plan window).
  - `deadline` (DateTime with timezone): The exclusive cutoff timestamp for on-time completion, set to the **next local midnight** (`scheduled_date + 1 day at 00:00:00` local time, converted to UTC).
  - `completed_at` (DateTime with timezone, nullable): Populated automatically with the server timestamp when the student marks it complete.

### 3.4 Derived Completion Statuses & Lifecycle Rules
- **One-Way Student Action**: Students can mark an assignment as completed with a single action. Students **cannot** directly undo or toggle off completion.
- **Tutor Reset Authority**: If a student marks an assignment complete by accident, the tutor (and only the tutor) can reset completion.
- **Auditability**: Every completion reset is immutably recorded in an audit table (`assignment_completion_audits`) tracking `assignment_id`, `reset_by_user_id`, `previous_completed_at`, `reset_at`, and an optional `reason`.
- **Re-completion**: If an assignment is reset and completed again later, a fresh `completed_at` server timestamp is recorded.
- **Derived Status Rules** (evaluated with exclusive deadline cutoff `< deadline`):
  1. **Pending**: `completed_at IS NULL AND current_time < deadline`.
  2. **Completed on time**: `completed_at IS NOT NULL AND completed_at < deadline`.
  3. **Completed late**: `completed_at IS NOT NULL AND completed_at >= deadline`.
  4. **Overdue and incomplete**: `completed_at IS NULL AND current_time >= deadline`.

### 3.5 External Examination Records
Students can manually record standardized or external exam performance:
- `exam_name`: Name of the mock or official exam (e.g., "National Mock Exam 1").
- `subject_id`: Optional link to a curriculum subject.
- `exam_date`: Date the exam was taken.
- `score`: Numeric score achieved (`score >= 0.00`).
- `max_score`: Optional/recommended total possible score (`max_score > 0.00`, with `score <= max_score`). Having `max_score` provides vital context for raw scores across different exam scoring scales (e.g. 80/100 vs. 650/800).
- `percentage`: Percentage representation (`0.00%` to `100.00%`). Automatically derived if `max_score` is provided (`(score / max_score) * 100`), or entered directly if the exam issues standard percentage/percentile results.
- `rank_in_exam`: Official ranking attained in that specific examination sitting (`rank_in_exam >= 1`).
- `notes`: Optional textual reflection or notes.
- *Strict Boundary*: No cross-student aggregate ranking or tutor-wide leaderboard is generated from these records.

### 3.6 Dashboards
- **Student Dashboard**:
  - Highlights active 14-day plan.
  - Lists "Today's Assignments" with one-click completion.
  - Displays plan completion percentage and progress bar.
  - Displays list of upcoming deadlines (next 48-72 hours) and overdue items.
  - Tabular view of past external exam entries.
- **Tutor Dashboard**:
  - High-level metric cards: Total active students, active plans, overall on-time completion rate.
  - Student overview table: Student name, active plan status, percentage completed, overdue assignment count.
  - "Attention Needed" filter/alert list: Students with multiple overdue assignments or no recent activity.
  - Quick-navigation to curriculum, student profiles, plan builder, and completion reset actions.

## 4. Non-Functional Requirements
- **Performance**: Instantaneous page loads (<100ms response time on typical VPS) using lightweight server-rendered HTML + HTMX fragments.
- **Data Isolation**: Strict boundary between student tenants. Students must never be able to access or modify records of any other student.
- **Reliability & Simplicity**: Zero external broker dependencies (no Redis, no Celery). Background tasks are avoided in favor of synchronous atomic operations suitable for ~100 concurrent students.
- **Auditability**: Completion timestamps are immutably captured at server time, and all completion resets are logged in an audit table.

## 5. Architectural Decisions on Previous Ambiguities
1. **Assignment Completion Reversibility**: Resolved. Students can mark complete, but cannot undo completion directly. Only the tutor can reset completions, creating an immutable audit entry. Re-completion captures a new server timestamp.
2. **Timezone Reference**: All internal timestamps are stored in UTC (`TIMESTAMPTZ`). Deadlines are computed using the next local midnight (`scheduled_date + 1 day at 00:00:00` in the student's designated timezone) as an exclusive cutoff (`completed_at < deadline`).
3. **Study Plan Concurrency**: Resolved. Enforced at most one `PUBLISHED` study plan per student at a time via a PostgreSQL partial unique index.
4. **Study Plan Duration**: Exactly 14 calendar days (`end_date = start_date + 13 days`). All assignments must fall within this window.
