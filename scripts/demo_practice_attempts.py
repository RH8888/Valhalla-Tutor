"""Generate realistic student practice attempts, answers, and scored results."""
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.models.practice_exam import (
    PracticeExam,
    StudentPracticeAttempt,
    StudentPracticeBookletAttempt,
    StudentPracticeAnswer,
)
from app.models.user import User


def generate_demo_practice_attempts(
    db: Session,
    exams: list[PracticeExam],
    students: list[User],
) -> None:
    now = datetime.now(timezone.utc)

    for exam in exams:
        assigned_students = [
            s for s in students
            if s.grade == exam.grade and s.academic_track_id == exam.academic_track_id
        ]
        booklets = sorted(exam.booklets, key=lambda b: b.order_index)

        for s_idx, student in enumerate(assigned_students):
            existing = db.query(StudentPracticeAttempt).filter(
                StudentPracticeAttempt.practice_exam_id == exam.id,
                StudentPracticeAttempt.student_id == student.id,
            ).first()
            if existing:
                continue

            is_top = "top" in student.username or "_1" in student.username
            is_in_progress = (s_idx == len(assigned_students) - 1)  # Last student in progress

            started_time = now - timedelta(days=3, hours=s_idx)
            attempt = StudentPracticeAttempt(
                student_id=student.id,
                practice_exam_id=exam.id,
                is_timed=True,
                status="IN_PROGRESS" if is_in_progress else "COMPLETED",
                started_at=started_time,
                completed_at=None if is_in_progress else started_time + timedelta(minutes=65),
            )
            db.add(attempt)
            db.flush()

            total_correct = 0
            total_incorrect = 0
            total_unanswered = 0

            # Generate booklet attempts
            for b_idx, booklet in enumerate(booklets):
                if is_in_progress and b_idx > 0:
                    break  # Second booklet not started yet

                b_start = started_time + timedelta(minutes=b_idx * 35)
                b_attempt = StudentPracticeBookletAttempt(
                    attempt_id=attempt.id,
                    booklet_id=booklet.id,
                    started_at=b_start,
                    expires_at=b_start + timedelta(minutes=booklet.duration_minutes or 30),
                    is_locked=not is_in_progress,
                    locked_at=None if is_in_progress else b_start + timedelta(minutes=booklet.duration_minutes or 30),
                )
                db.add(b_attempt)
                db.flush()

                # Generate answers for questions in this booklet
                q_range = range(booklet.question_start, booklet.question_end + 1)
                for q_num in q_range:
                    if is_in_progress and q_num > booklet.question_start + 8:
                        continue  # In progress: unanswered remaining questions

                    q_obj = next((q for q in exam.questions if q.question_number == q_num), None)
                    correct_choice = q_obj.correct_choice if q_obj else 1

                    # Choice simulation based on profile
                    if is_top:
                        choice = correct_choice if (q_num % 6 != 0) else ((correct_choice % 4) + 1)
                    else:
                        mod = q_num % 4
                        choice = correct_choice if mod in [0, 1] else (((correct_choice + 1) % 4) + 1 if mod == 2 else None)

                    if choice is None:
                        is_corr = None
                        total_unanswered += 1
                    elif choice == correct_choice:
                        is_corr = True
                        total_correct += 1
                    else:
                        is_corr = False
                        total_incorrect += 1

                    db.add(StudentPracticeAnswer(
                        attempt_id=attempt.id,
                        booklet_attempt_id=b_attempt.id,
                        question_number=q_num,
                        selected_choice=choice,
                        is_correct=is_corr,
                    ))

            total_q = len(exam.questions)
            if not is_in_progress and total_q > 0:
                raw_pct = ((3 * total_correct - total_incorrect) / (3 * total_q)) * 100
                overall_pct = round(max(0.0, raw_pct), 2)
            else:
                overall_pct = 0.0

            attempt.total_correct = total_correct
            attempt.total_incorrect = total_incorrect
            attempt.total_unanswered = total_unanswered
            attempt.overall_percentage = overall_pct

    db.flush()
