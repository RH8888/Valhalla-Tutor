import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy import desc
from sqlalchemy.orm import Session, joinedload

from app.core.timezone import now_utc
from app.models.practice_exam import (
    PracticeExam,
    PracticeExamAssignment,
    PracticeExamBooklet,
    PracticeExamQuestion,
    PracticeExamReportingGroup,
    StudentPracticeAnswer,
    StudentPracticeAttempt,
    StudentPracticeBookletAttempt,
)
from app.models.subject import Subject
from app.models.track import AcademicTrack
from app.models.user import User
from app.services.academic_service import get_subject_by_id, get_track_by_id


class PracticeExamNotFoundError(Exception):
    pass


class PracticeExamValidationError(Exception):
    pass


class PracticeExamLockedError(Exception):
    pass


def create_practice_exam(
    db: Session,
    title: str,
    grade: str,
    academic_track_id: uuid.UUID,
    description: Optional[str] = None,
    is_timed: bool = True,
    allow_retake: bool = False,
) -> PracticeExam:
    clean_title = (title or "").strip()
    if not clean_title:
        raise PracticeExamValidationError("Practice exam title cannot be empty.")

    clean_grade = (grade or "").strip()
    if clean_grade not in ["10", "11", "12"]:
        raise PracticeExamValidationError("Valid academic grade (10, 11, or 12) is required.")

    track = get_track_by_id(db, academic_track_id)
    if not track:
        raise PracticeExamValidationError(f"Academic track with id {academic_track_id} not found.")

    exam = PracticeExam(
        title=clean_title,
        description=description.strip() if description and description.strip() else None,
        grade=clean_grade,
        academic_track_id=track.id,
        is_timed=is_timed,
        allow_retake=allow_retake,
        is_active=True,
    )
    db.add(exam)
    db.commit()
    db.refresh(exam)
    return exam


def get_practice_exam_by_id(db: Session, exam_id: uuid.UUID) -> Optional[PracticeExam]:
    return (
        db.query(PracticeExam)
        .options(
            joinedload(PracticeExam.track),
            joinedload(PracticeExam.booklets),
            joinedload(PracticeExam.reporting_groups),
            joinedload(PracticeExam.questions).joinedload(PracticeExamQuestion.subject),
            joinedload(PracticeExam.questions).joinedload(PracticeExamQuestion.reporting_group),
            joinedload(PracticeExam.assignments).joinedload(PracticeExamAssignment.student),
        )
        .filter(PracticeExam.id == exam_id)
        .first()
    )


def list_practice_exams(
    db: Session,
    grade: Optional[str] = None,
    track_id: Optional[uuid.UUID] = None,
    include_inactive: bool = True,
) -> List[PracticeExam]:
    query = db.query(PracticeExam).options(
        joinedload(PracticeExam.track),
        joinedload(PracticeExam.booklets),
    )
    if not include_inactive:
        query = query.filter(PracticeExam.is_active.is_(True))
    if grade:
        query = query.filter(PracticeExam.grade == grade)
    if track_id:
        query = query.filter(PracticeExam.academic_track_id == track_id)
    return query.order_by(desc(PracticeExam.created_at)).all()


def add_practice_exam_booklet(
    db: Session,
    practice_exam_id: uuid.UUID,
    title: str,
    pdf_file_path: str,
    pdf_file_name: str,
    question_start: int,
    question_end: int,
    duration_minutes: Optional[int] = None,
    order_index: Optional[int] = None,
) -> PracticeExamBooklet:
    exam = get_practice_exam_by_id(db, practice_exam_id)
    if not exam:
        raise PracticeExamNotFoundError(f"Practice exam with id {practice_exam_id} not found.")

    if question_start <= 0 or question_end < question_start:
        raise PracticeExamValidationError("Invalid question range: start must be >= 1 and end >= start.")

    for b in exam.booklets:
        if max(question_start, b.question_start) <= min(question_end, b.question_end):
            raise PracticeExamValidationError(
                f"Question range {question_start}–{question_end} overlaps with booklet '{b.title}' ({b.question_start}–{b.question_end})."
            )

    if order_index is None:
        order_index = len(exam.booklets) + 1

    booklet = PracticeExamBooklet(
        practice_exam_id=exam.id,
        order_index=order_index,
        title=title.strip() if title else f"Booklet {order_index}",
        pdf_file_path=pdf_file_path,
        pdf_file_name=pdf_file_name,
        question_start=question_start,
        question_end=question_end,
        duration_minutes=duration_minutes if duration_minutes and duration_minutes > 0 else None,
    )
    db.add(booklet)
    db.commit()
    db.refresh(booklet)
    return booklet


def create_practice_reporting_group(
    db: Session,
    practice_exam_id: uuid.UUID,
    title: str,
) -> PracticeExamReportingGroup:
    exam = get_practice_exam_by_id(db, practice_exam_id)
    if not exam:
        raise PracticeExamNotFoundError(f"Practice exam with id {practice_exam_id} not found.")
    clean_title = (title or "").strip()
    if not clean_title:
        raise PracticeExamValidationError("Reporting group title cannot be empty.")

    group = PracticeExamReportingGroup(
        practice_exam_id=exam.id,
        title=clean_title,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def configure_practice_exam_questions(
    db: Session,
    practice_exam_id: uuid.UUID,
    question_definitions: List[Dict[str, Any]],
) -> List[PracticeExamQuestion]:
    """Configure questions, answer key (1, 2, 3, 4), and subject/reporting group assignment."""
    exam = get_practice_exam_by_id(db, practice_exam_id)
    if not exam:
        raise PracticeExamNotFoundError(f"Practice exam with id {practice_exam_id} not found.")

    # Preserve historical records: forbid reconfiguring questions once attempts exist
    has_attempts = db.query(StudentPracticeAttempt).filter(
        StudentPracticeAttempt.practice_exam_id == exam.id
    ).first()
    if has_attempts:
        raise PracticeExamValidationError(
            "Cannot reconfigure questions for a practice exam with existing student attempts."
        )

    # Remove existing questions to allow clean reconfiguration
    for q in list(exam.questions):
        db.delete(q)
    db.flush()

    track_subject_ids = {s.id for s in exam.track.subjects}
    created_questions = []
    seen_numbers: Set[int] = set()

    for item in question_definitions:
        q_num = int(item["question_number"])
        if q_num in seen_numbers:
            raise PracticeExamValidationError(f"Duplicate question number {q_num} in exam configuration.")
        seen_numbers.add(q_num)

        choice = int(item["correct_choice"])
        if choice not in [1, 2, 3, 4]:
            raise PracticeExamValidationError(f"Question {q_num} correct choice must be 1, 2, 3, or 4.")

        sub_id = uuid.UUID(str(item["subject_id"]))
        if sub_id not in track_subject_ids:
            sub = get_subject_by_id(db, sub_id)
            sub_name = sub.name if sub else str(sub_id)
            raise PracticeExamValidationError(f"Subject '{sub_name}' is not in track '{exam.track.name}'.")

        group_id = uuid.UUID(str(item["reporting_group_id"])) if item.get("reporting_group_id") else None

        question = PracticeExamQuestion(
            practice_exam_id=exam.id,
            question_number=q_num,
            correct_choice=choice,
            subject_id=sub_id,
            reporting_group_id=group_id,
        )
        db.add(question)
        created_questions.append(question)

    db.commit()
    return created_questions


def assign_practice_exam_to_students(
    db: Session,
    practice_exam_id: uuid.UUID,
    student_ids: List[uuid.UUID],
) -> None:
    exam = get_practice_exam_by_id(db, practice_exam_id)
    if not exam:
        raise PracticeExamNotFoundError(f"Practice exam with id {practice_exam_id} not found.")

    for sid in student_ids:
        existing = db.query(PracticeExamAssignment).filter(
            PracticeExamAssignment.practice_exam_id == exam.id,
            PracticeExamAssignment.student_id == sid,
        ).first()
        if not existing:
            assignment = PracticeExamAssignment(practice_exam_id=exam.id, student_id=sid)
            db.add(assignment)
    db.commit()


def get_student_available_practice_exams(db: Session, student: User) -> List[Dict[str, Any]]:
    """Retrieve practice exams eligible for student by grade/track or direct assignment."""
    query = (
        db.query(PracticeExam)
        .options(
            joinedload(PracticeExam.track),
            joinedload(PracticeExam.booklets),
            joinedload(PracticeExam.attempts),
        )
        .filter(PracticeExam.is_active.is_(True))
    )
    all_exams = query.order_by(desc(PracticeExam.created_at)).all()
    results = []

    for exam in all_exams:
        # Check direct assignment or grade + track eligibility
        has_direct_assignment = any(a.student_id == student.id for a in exam.assignments)
        is_eligible_by_profile = (
            student.grade == exam.grade and student.academic_track_id == exam.academic_track_id
        )
        if has_direct_assignment or is_eligible_by_profile:
            student_attempts = [att for att in exam.attempts if att.student_id == student.id]
            student_attempts.sort(key=lambda a: a.started_at)
            exam.latest_attempt = student_attempts[-1] if student_attempts else None
            results.append(exam)
    return results


def start_practice_attempt(
    db: Session,
    student: User,
    practice_exam_id: uuid.UUID,
) -> StudentPracticeAttempt:
    # Concurrency control: lock student row to serialize concurrent attempt starts
    db.query(User.id).filter(User.id == student.id).with_for_update().first()

    exam = get_practice_exam_by_id(db, practice_exam_id)
    if not exam:
        raise PracticeExamNotFoundError(f"Practice exam with id {practice_exam_id} not found.")

    has_direct_assignment = any(a.student_id == student.id for a in exam.assignments)
    is_eligible = student.grade == exam.grade and student.academic_track_id == exam.academic_track_id
    if not (has_direct_assignment or is_eligible):
        raise PracticeExamValidationError("You are not eligible to take this practice exam.")

    if not exam.booklets:
        raise PracticeExamValidationError("This practice exam has no PDF booklets configured.")

    # Return existing in-progress attempt if available
    existing = (
        db.query(StudentPracticeAttempt)
        .filter(
            StudentPracticeAttempt.student_id == student.id,
            StudentPracticeAttempt.practice_exam_id == exam.id,
            StudentPracticeAttempt.status == "IN_PROGRESS",
        )
        .first()
    )
    if existing:
        return existing

    # If already completed and retakes are not permitted, forbid starting a new attempt
    completed_attempt = (
        db.query(StudentPracticeAttempt)
        .filter(
            StudentPracticeAttempt.student_id == student.id,
            StudentPracticeAttempt.practice_exam_id == exam.id,
            StudentPracticeAttempt.status == "COMPLETED",
        )
        .first()
    )
    if completed_attempt and not getattr(exam, "allow_retake", False):
        raise PracticeExamValidationError("Retakes are not permitted for this practice exam. You may review your completed results.")

    attempt = StudentPracticeAttempt(
        student_id=student.id,
        practice_exam_id=exam.id,
        is_timed=exam.is_timed,
        status="IN_PROGRESS",
        started_at=now_utc(),
    )
    db.add(attempt)
    db.flush()

    # Unlock first booklet
    first_booklet = exam.booklets[0]
    expires = None
    if exam.is_timed and first_booklet.duration_minutes:
        expires = attempt.started_at + timedelta(minutes=first_booklet.duration_minutes)

    b_attempt = StudentPracticeBookletAttempt(
        attempt_id=attempt.id,
        booklet_id=first_booklet.id,
        started_at=attempt.started_at,
        expires_at=expires,
        is_locked=False,
    )
    db.add(b_attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def get_student_booklet_state(
    db: Session,
    attempt_id: uuid.UUID,
    booklet_id: uuid.UUID,
) -> Dict[str, Any]:
    """Retrieve booklet questions, current timer state, and enforce server-side expiration."""
    attempt = db.query(StudentPracticeAttempt).filter(StudentPracticeAttempt.id == attempt_id).first()
    if not attempt:
        raise PracticeExamNotFoundError("Attempt not found.")

    booklet = db.query(PracticeExamBooklet).filter(PracticeExamBooklet.id == booklet_id).first()
    if not booklet:
        raise PracticeExamNotFoundError("Booklet not found.")

    b_attempt = (
        db.query(StudentPracticeBookletAttempt)
        .filter(
            StudentPracticeBookletAttempt.attempt_id == attempt.id,
            StudentPracticeBookletAttempt.booklet_id == booklet.id,
        )
        .first()
    )

    now = now_utc()
    # Server-side timer enforcement
    if b_attempt and not b_attempt.is_locked and attempt.is_timed and b_attempt.expires_at:
        exp = b_attempt.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if now >= exp:
            b_attempt.is_locked = True
            b_attempt.locked_at = exp
            db.commit()

    # Fetch answers entered so far
    answers = (
        db.query(StudentPracticeAnswer)
        .filter(StudentPracticeAnswer.attempt_id == attempt.id)
        .all()
    )
    answers_map = {a.question_number: a.selected_choice for a in answers}

    # Questions in this booklet range
    questions = (
        db.query(PracticeExamQuestion)
        .filter(
            PracticeExamQuestion.practice_exam_id == attempt.practice_exam_id,
            PracticeExamQuestion.question_number >= booklet.question_start,
            PracticeExamQuestion.question_number <= booklet.question_end,
        )
        .order_by(PracticeExamQuestion.question_number)
        .all()
    )

    remaining_seconds = 0
    if b_attempt and attempt.is_timed and b_attempt.expires_at and not b_attempt.is_locked:
        exp = b_attempt.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        diff = (exp - now).total_seconds()
        remaining_seconds = max(0, int(diff))

    return {
        "attempt": attempt,
        "booklet": booklet,
        "booklet_attempt": b_attempt,
        "is_locked": b_attempt.is_locked if b_attempt else True,
        "remaining_seconds": remaining_seconds,
        "questions": questions,
        "answers_map": answers_map,
    }


def submit_booklet_answers(
    db: Session,
    student: User,
    attempt_id: uuid.UUID,
    booklet_id: uuid.UUID,
    answers: Dict[int, Optional[int]],
    advance_to_next: bool = False,
) -> Dict[str, Any]:
    """Save answers for questions in a booklet and optionally lock/advance to next booklet."""
    state = get_student_booklet_state(db, attempt_id, booklet_id)
    attempt = state["attempt"]
    booklet = state["booklet"]

    if attempt.student_id != student.id:
        raise PracticeExamValidationError("Unauthorized access to this practice exam attempt.")

    # Concurrency control: atomically lock the booklet attempt row to prevent writes after expiration/lock
    b_attempt = (
        db.query(StudentPracticeBookletAttempt)
        .filter(
            StudentPracticeBookletAttempt.attempt_id == attempt.id,
            StudentPracticeBookletAttempt.booklet_id == booklet.id,
        )
        .with_for_update()
        .first()
    )
    if not b_attempt or b_attempt.is_locked:
        raise PracticeExamLockedError("This booklet is locked. Answers cannot be modified.")

    now = now_utc()
    if attempt.is_timed and b_attempt.expires_at:
        exp = b_attempt.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if now >= exp:
            b_attempt.is_locked = True
            b_attempt.locked_at = exp
            db.commit()
            raise PracticeExamLockedError("Time has expired for this booklet. Answers cannot be modified.")

    valid_q_nums = {
        q.question_number for q in state["questions"]
        if booklet.question_start <= q.question_number <= booklet.question_end
    }

    for q_num, choice in answers.items():
        if q_num not in valid_q_nums:
            continue
        if choice is not None and choice not in [1, 2, 3, 4]:
            raise PracticeExamValidationError(f"Invalid choice '{choice}' for question {q_num}. Must be 1, 2, 3, or 4.")

        ans_rec = (
            db.query(StudentPracticeAnswer)
            .filter(
                StudentPracticeAnswer.attempt_id == attempt.id,
                StudentPracticeAnswer.question_number == q_num,
            )
            .first()
        )
        if not ans_rec:
            ans_rec = StudentPracticeAnswer(
                attempt_id=attempt.id,
                booklet_attempt_id=b_attempt.id,
                question_number=q_num,
                selected_choice=choice,
            )
            db.add(ans_rec)
        else:
            if ans_rec.booklet_attempt_id != b_attempt.id:
                raise PracticeExamLockedError(f"Question {q_num} belongs to another booklet and cannot be modified.")
            ans_rec.selected_choice = choice
            ans_rec.booklet_attempt_id = b_attempt.id

    db.flush()

    if advance_to_next:
        # Lock current booklet permanently
        b_attempt.is_locked = True
        b_attempt.locked_at = now

        # Find next booklet
        exam = attempt.practice_exam
        next_booklet = next(
            (b for b in exam.booklets if b.order_index > booklet.order_index),
            None,
        )

        if next_booklet:
            # Start next booklet
            next_expires = None
            if attempt.is_timed and next_booklet.duration_minutes:
                next_expires = now + timedelta(minutes=next_booklet.duration_minutes)

            next_b_attempt = StudentPracticeBookletAttempt(
                attempt_id=attempt.id,
                booklet_id=next_booklet.id,
                started_at=now,
                expires_at=next_expires,
                is_locked=False,
            )
            db.add(next_b_attempt)
            db.commit()
            return {"advanced": True, "completed": False, "next_booklet_id": str(next_booklet.id)}
        else:
            # No more booklets, finalize attempt and compute grades
            attempt.status = "COMPLETED"
            attempt.completed_at = now
            db.commit()
            calculate_practice_exam_results(db, attempt.id)
            return {"advanced": False, "completed": True, "next_booklet_id": None}

    db.commit()
    return {"advanced": False, "completed": False, "next_booklet_id": None}


def calculate_practice_exam_results(db: Session, attempt_id: uuid.UUID) -> StudentPracticeAttempt:
    """Calculate correct, incorrect, unanswered, and percentages per group and overall."""
    attempt = (
        db.query(StudentPracticeAttempt)
        .options(
            joinedload(StudentPracticeAttempt.practice_exam).joinedload(PracticeExam.questions),
            joinedload(StudentPracticeAttempt.answers),
        )
        .filter(StudentPracticeAttempt.id == attempt_id)
        .first()
    )
    if not attempt:
        raise PracticeExamNotFoundError("Attempt not found.")
    if attempt.status != "COMPLETED":
        raise PracticeExamValidationError("Results and answer-key feedback are only available after the exam attempt is completed.")

    exam = attempt.practice_exam
    questions_by_num = {q.question_number: q for q in exam.questions}
    answers_by_num = {a.question_number: a for a in attempt.answers}

    total_correct = 0
    total_incorrect = 0
    total_unanswered = 0

    for q_num, q in questions_by_num.items():
        ans = answers_by_num.get(q_num)
        choice = ans.selected_choice if ans else None
        if choice is not None:
            if choice == q.correct_choice:
                total_correct += 1
                if ans:
                    ans.is_correct = True
            else:
                total_incorrect += 1
                if ans:
                    ans.is_correct = False
        else:
            total_unanswered += 1
            if ans:
                ans.is_correct = None

    total_q = len(exam.questions)
    if total_q > 0:
        raw_pct = ((3 * total_correct - total_incorrect) / (3 * total_q)) * 100
        overall_pct = round(raw_pct, 2)
    else:
        overall_pct = 0.0

    attempt.total_correct = total_correct
    attempt.total_incorrect = total_incorrect
    attempt.total_unanswered = total_unanswered
    attempt.overall_percentage = overall_pct
    db.commit()
    db.refresh(attempt)
    return attempt


def get_practice_exam_detailed_results(db: Session, attempt_id: uuid.UUID) -> Dict[str, Any]:
    """Breakdown of practice exam results by configured reporting groups and individual subjects."""
    attempt = (
        db.query(StudentPracticeAttempt)
        .options(
            joinedload(StudentPracticeAttempt.student),
            joinedload(StudentPracticeAttempt.practice_exam).joinedload(PracticeExam.reporting_groups),
            joinedload(StudentPracticeAttempt.practice_exam)
            .joinedload(PracticeExam.questions)
            .joinedload(PracticeExamQuestion.subject),
            joinedload(StudentPracticeAttempt.practice_exam)
            .joinedload(PracticeExam.questions)
            .joinedload(PracticeExamQuestion.reporting_group),
            joinedload(StudentPracticeAttempt.answers),
        )
        .filter(StudentPracticeAttempt.id == attempt_id)
        .first()
    )
    if not attempt:
        raise PracticeExamNotFoundError("Attempt not found.")
    if attempt.status != "COMPLETED":
        raise PracticeExamValidationError("Results and answer-key feedback are only available after the exam attempt is completed.")

    exam = attempt.practice_exam
    questions = exam.questions
    answers_map = {a.question_number: a.selected_choice for a in attempt.answers}

    # Group questions by reporting group or subject
    groups_data: Dict[str, Dict[str, Any]] = {}
    subjects_data: Dict[str, Dict[str, Any]] = {}

    for q in questions:
        choice = answers_map.get(q.question_number)
        is_corr = choice == q.correct_choice if choice is not None else False
        is_incorr = choice is not None and choice != q.correct_choice
        is_unans = choice is None

        # 1. Reporting Group breakdown
        g_name = q.reporting_group.title if q.reporting_group else q.subject.name
        if g_name not in groups_data:
            groups_data[g_name] = {"name": g_name, "total": 0, "correct": 0, "incorrect": 0, "unanswered": 0}
        groups_data[g_name]["total"] += 1
        if is_corr:
            groups_data[g_name]["correct"] += 1
        elif is_incorr:
            groups_data[g_name]["incorrect"] += 1
        elif is_unans:
            groups_data[g_name]["unanswered"] += 1

        # 2. Individual Subject breakdown
        s_name = q.subject.name
        if s_name not in subjects_data:
            subjects_data[s_name] = {"name": s_name, "total": 0, "correct": 0, "incorrect": 0, "unanswered": 0}
        subjects_data[s_name]["total"] += 1
        if is_corr:
            subjects_data[s_name]["correct"] += 1
        elif is_incorr:
            subjects_data[s_name]["incorrect"] += 1
        elif is_unans:
            subjects_data[s_name]["unanswered"] += 1

    for d in [groups_data, subjects_data]:
        for item in d.values():
            tot = item["total"]
            c = item["correct"]
            inc = item["incorrect"]
            item["percentage"] = round(((3 * c - inc) / (3 * tot)) * 100, 2) if tot > 0 else 0.0

    return {
        "attempt": attempt,
        "exam": exam,
        "overall_percentage": attempt.overall_percentage,
        "total_correct": attempt.total_correct,
        "total_incorrect": attempt.total_incorrect,
        "total_unanswered": attempt.total_unanswered,
        "total_questions": len(questions),
        "reporting_groups": list(groups_data.values()),
        "individual_subjects": list(subjects_data.values()),
    }
