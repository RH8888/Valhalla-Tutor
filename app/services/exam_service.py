import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy import desc
from sqlalchemy.orm import Session, joinedload

from app.core.timezone import now_utc
from app.models.exam import (
    Exam,
    ExamSession,
    ExamSubjectConfiguration,
    ExamTrackConfiguration,
    StudentExamResult,
    StudentExamSubjectResult,
    ExternalExamAssignment,
    HistoricalExamResult,
    HistoricalExamSubjectResult,
)
from app.models.subject import Subject
from app.models.track import AcademicTrack
from app.models.user import User
from app.services.academic_service import get_student_effective_subjects, get_subject_by_id, get_track_by_id


class ExamNotFoundError(Exception):
    pass


class ExamSessionNotFoundError(Exception):
    pass


class ExamValidationError(Exception):
    pass


class ExamResultNotFoundError(Exception):
    pass


class DuplicateExamResultError(Exception):
    pass


def create_exam(
    db: Session,
    title: str,
    description: Optional[str] = None,
) -> Exam:
    clean_title = (title or "").strip()
    if not clean_title:
        raise ExamValidationError("Exam title cannot be empty.")

    exam = Exam(
        title=clean_title,
        description=description.strip() if description and description.strip() else None,
        is_active=True,
    )
    db.add(exam)
    db.commit()
    db.refresh(exam)
    return exam


def update_exam(
    db: Session,
    exam_id: uuid.UUID,
    title: str,
    description: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> Exam:
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")

    clean_title = (title or "").strip()
    if not clean_title:
        raise ExamValidationError("Exam title cannot be empty.")

    exam.title = clean_title
    exam.description = description.strip() if description and description.strip() else None
    if is_active is not None:
        exam.is_active = is_active
    db.commit()
    db.refresh(exam)
    return exam


def archive_exam(db: Session, exam_id: uuid.UUID) -> Exam:
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    exam.is_active = False
    db.commit()
    db.refresh(exam)
    return exam


def get_exam_by_id(db: Session, exam_id: uuid.UUID) -> Optional[Exam]:
    return db.query(Exam).filter(Exam.id == exam_id).first()


def list_exams(db: Session, include_inactive: bool = True) -> List[Exam]:
    query = db.query(Exam)
    if not include_inactive:
        query = query.filter(Exam.is_active.is_(True))
    return query.order_by(Exam.created_at.desc()).all()



def get_exam_session_by_id(db: Session, session_id: uuid.UUID) -> Optional[ExamSession]:
    return (
        db.query(ExamSession)
        .options(
            joinedload(ExamSession.exam),
            joinedload(ExamSession.track_configs)
            .joinedload(ExamTrackConfiguration.track),
            joinedload(ExamSession.track_configs)
            .joinedload(ExamTrackConfiguration.subject_configs)
            .joinedload(ExamSubjectConfiguration.subject),
            joinedload(ExamSession.results)
            .joinedload(StudentExamResult.student),
            joinedload(ExamSession.results)
            .joinedload(StudentExamResult.subject_results)
            .joinedload(StudentExamSubjectResult.subject),
        )
        .filter(ExamSession.id == session_id)
        .first()
    )


def list_exam_sessions(
    db: Session,
    track_id: Optional[uuid.UUID] = None,
) -> List[ExamSession]:
    query = (
        db.query(ExamSession)
        .options(
            joinedload(ExamSession.exam),
            joinedload(ExamSession.track_configs).joinedload(ExamTrackConfiguration.track),
        )
    )
    if track_id is not None:
        query = query.join(ExamTrackConfiguration).filter(ExamTrackConfiguration.track_id == track_id)
    return query.order_by(desc(ExamSession.date), desc(ExamSession.created_at)).all()


def create_exam_session(
    db: Session,
    exam_id: uuid.UUID,
    exam_date: date,
    title: Optional[str] = None,
    track_subjects_map: Optional[Dict[uuid.UUID, List[uuid.UUID]]] = None,
) -> ExamSession:
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    if not exam.is_active:
        raise ExamValidationError(f"Cannot schedule session for archived exam '{exam.title}'.")

    if not track_subjects_map or len(track_subjects_map) == 0:
        raise ExamValidationError("At least one academic track must be configured for the exam.")

    session = ExamSession(
        exam_id=exam.id,
        date=exam_date,
        title=title.strip() if title and title.strip() else None,
    )
    db.add(session)
    db.flush()

    for track_id, subject_ids in track_subjects_map.items():
        track = get_track_by_id(db, track_id)
        if not track:
            raise ExamValidationError(f"Academic track with id {track_id} not found.")
        if not subject_ids:
            raise ExamValidationError(f"At least one subject must be selected for track '{track.name}'.")

        track_config = ExamTrackConfiguration(
            exam_session_id=session.id,
            track_id=track.id,
        )
        db.add(track_config)
        db.flush()

        track_valid_subject_ids = {s.id for s in track.subjects}
        for sub_id in subject_ids:
            if sub_id not in track_valid_subject_ids:
                sub = get_subject_by_id(db, sub_id)
                sub_name = sub.name if sub else str(sub_id)
                raise ExamValidationError(
                    f"Subject '{sub_name}' is not valid for academic track '{track.name}'."
                )
            subj_config = ExamSubjectConfiguration(
                exam_track_config_id=track_config.id,
                subject_id=sub_id,
            )
            db.add(subj_config)

    db.commit()
    db.refresh(session)
    return get_exam_session_by_id(db, session.id)


def update_exam_session(
    db: Session,
    session_id: uuid.UUID,
    exam_date: date,
    title: Optional[str] = None,
    track_subjects_map: Optional[Dict[uuid.UUID, List[uuid.UUID]]] = None,
) -> ExamSession:
    session = get_exam_session_by_id(db, session_id)
    if not session:
        raise ExamSessionNotFoundError(f"Exam session with id {session_id} not found.")

    session.date = exam_date
    session.title = title.strip() if title and title.strip() else None

    if track_subjects_map is not None:
        if len(track_subjects_map) == 0:
            raise ExamValidationError("At least one academic track must be configured for the exam.")

        # Remove existing configurations and recreate
        for tc in list(session.track_configs):
            db.delete(tc)
        db.flush()

        for track_id, subject_ids in track_subjects_map.items():
            track = get_track_by_id(db, track_id)
            if not track:
                raise ExamValidationError(f"Academic track with id {track_id} not found.")
            if not subject_ids:
                raise ExamValidationError(f"At least one subject must be selected for track '{track.name}'.")

            track_config = ExamTrackConfiguration(
                exam_session_id=session.id,
                track_id=track.id,
            )
            db.add(track_config)
            db.flush()

            track_valid_subject_ids = {s.id for s in track.subjects}
            for sub_id in subject_ids:
                if sub_id not in track_valid_subject_ids:
                    sub = get_subject_by_id(db, sub_id)
                    sub_name = sub.name if sub else str(sub_id)
                    raise ExamValidationError(
                        f"Subject '{sub_name}' is not valid for academic track '{track.name}'."
                    )
                subj_config = ExamSubjectConfiguration(
                    exam_track_config_id=track_config.id,
                    subject_id=sub_id,
                )
                db.add(subj_config)

    db.commit()
    db.refresh(session)
    return get_exam_session_by_id(db, session.id)


def delete_exam_session(db: Session, session_id: uuid.UUID) -> None:
    session = get_exam_session_by_id(db, session_id)
    if not session:
        raise ExamSessionNotFoundError(f"Exam session with id {session_id} not found.")
    db.delete(session)
    db.commit()


def get_student_available_exams(db: Session, student: User) -> Dict[str, Any]:
    if not student.academic_track_id:
        return {"upcoming": [], "past": [], "track_assigned": False}

    all_sessions = (
        db.query(ExamSession)
        .join(ExamTrackConfiguration, ExamTrackConfiguration.exam_session_id == ExamSession.id)
        .filter(ExamTrackConfiguration.track_id == student.academic_track_id)
        .options(
            joinedload(ExamSession.exam),
            joinedload(ExamSession.track_configs)
            .joinedload(ExamTrackConfiguration.subject_configs)
            .joinedload(ExamSubjectConfiguration.subject),
            joinedload(ExamSession.results)
            .joinedload(StudentExamResult.subject_results),
        )
        .order_by(desc(ExamSession.date))
        .all()
    )

    today = date.today()
    upcoming = []
    past = []

    for s in all_sessions:
        student_result = next((r for r in s.results if r.student_id == student.id), None)
        item = {
            "session": s,
            "result": student_result,
            "has_submitted": student_result is not None,
        }
        if s.date > today:
            upcoming.append(item)
        else:
            past.append(item)

    return {"upcoming": upcoming, "past": past, "track_assigned": True}


def get_student_exam_result(
    db: Session,
    student_id: uuid.UUID,
    exam_session_id: uuid.UUID,
) -> Optional[StudentExamResult]:
    return (
        db.query(StudentExamResult)
        .options(
            joinedload(StudentExamResult.student),
            joinedload(StudentExamResult.exam_session).joinedload(ExamSession.exam),
            joinedload(StudentExamResult.subject_results).joinedload(StudentExamSubjectResult.subject),
        )
        .filter(
            StudentExamResult.student_id == student_id,
            StudentExamResult.exam_session_id == exam_session_id,
        )
        .first()
    )


def get_student_exam_result_by_id(
    db: Session,
    result_id: uuid.UUID,
) -> Optional[StudentExamResult]:
    return (
        db.query(StudentExamResult)
        .options(
            joinedload(StudentExamResult.student),
            joinedload(StudentExamResult.exam_session).joinedload(ExamSession.exam),
            joinedload(StudentExamResult.subject_results).joinedload(StudentExamSubjectResult.subject),
        )
        .filter(StudentExamResult.id == result_id)
        .first()
    )


def submit_student_exam_result(
    db: Session,
    student: User,
    exam_session_id: uuid.UUID,
    subject_data: List[Dict[str, Any]],
    overall_rank: Optional[int] = None,
    notes: Optional[str] = None,
    report_card_file_path: Optional[str] = None,
    report_card_file_name: Optional[str] = None,
) -> StudentExamResult:
    if not student.academic_track_id:
        raise ExamValidationError("Student has no academic track assigned.")

    session = get_exam_session_by_id(db, exam_session_id)
    if not session:
        raise ExamSessionNotFoundError(f"Exam session with id {exam_session_id} not found.")

    track_config = next(
        (tc for tc in session.track_configs if tc.track_id == student.academic_track_id),
        None,
    )
    if not track_config:
        raise ExamValidationError("This exam is not available for your academic track.")

    existing_result = get_student_exam_result(db, student.id, session.id)
    if existing_result:
        raise DuplicateExamResultError("Results have already been submitted for this exam occurrence.")

    configured_subject_ids = {sc.subject_id for sc in track_config.subject_configs}
    effective_subjects = get_student_effective_subjects(student)
    effective_subject_ids = {s.id for s in effective_subjects}
    allowed_subject_ids = configured_subject_ids.intersection(effective_subject_ids)

    if not subject_data:
        raise ExamValidationError("At least one subject result must be submitted.")

    clean_rank = None
    if overall_rank is not None:
        try:
            clean_rank = int(overall_rank)
            if clean_rank <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise ExamValidationError("Overall rank must be a positive integer if provided.")

    seen_subjects: Set[uuid.UUID] = set()
    parsed_items = []
    for item in subject_data:
        sub_id = item.get("subject_id")
        if isinstance(sub_id, str):
            sub_id = uuid.UUID(sub_id)
        if not sub_id or sub_id not in allowed_subject_ids:
            sub = get_subject_by_id(db, sub_id) if sub_id else None
            sub_name = sub.name if sub else str(sub_id)
            raise ExamValidationError(
                f"Subject '{sub_name}' is not allowed for your track in this exam."
            )
        if sub_id in seen_subjects:
            raise ExamValidationError("Duplicate subject entry in submitted results.")
        seen_subjects.add(sub_id)

        try:
            correct = int(item.get("correct_answers", 0))
            incorrect = int(item.get("incorrect_answers", 0))
        except (ValueError, TypeError):
            raise ExamValidationError("Correct and incorrect answers must be valid integers.")

        if correct < 0 or incorrect < 0:
            raise ExamValidationError("Correct and incorrect counts must be non-negative integers.")

        try:
            percentage = float(item.get("percentage", 0.0))
        except (ValueError, TypeError):
            raise ExamValidationError("Percentage must be a valid number.")

        if percentage < 0.0 or percentage > 100.0:
            raise ExamValidationError("Percentage must be between 0 and 100.")

        parsed_items.append((sub_id, correct, incorrect, percentage))

    result = StudentExamResult(
        student_id=student.id,
        exam_session_id=session.id,
        overall_rank=clean_rank,
        notes=notes.strip() if notes and notes.strip() else None,
        report_card_file_path=report_card_file_path,
        report_card_file_name=report_card_file_name,
    )
    db.add(result)
    db.flush()

    for sub_id, correct, incorrect, percentage in parsed_items:
        subject_result = StudentExamSubjectResult(
            student_exam_result_id=result.id,
            subject_id=sub_id,
            correct_answers=correct,
            incorrect_answers=incorrect,
            percentage=percentage,
        )
        db.add(subject_result)

    db.commit()
    return get_student_exam_result_by_id(db, result.id)


def update_student_exam_result(
    db: Session,
    student: User,
    result_id: uuid.UUID,
    subject_data: List[Dict[str, Any]],
    overall_rank: Optional[int] = None,
    notes: Optional[str] = None,
    report_card_file_path: Optional[str] = None,
    report_card_file_name: Optional[str] = None,
) -> StudentExamResult:
    result = get_student_exam_result_by_id(db, result_id)
    if not result:
        raise ExamResultNotFoundError(f"Exam result with id {result_id} not found.")

    if result.student_id != student.id:
        raise ExamValidationError("You are not authorized to edit this result.")

    session = result.exam_session
    track_config = next(
        (tc for tc in session.track_configs if tc.track_id == student.academic_track_id),
        None,
    )
    if not track_config:
        raise ExamValidationError("This exam configuration is no longer valid for your track.")

    configured_subject_ids = {sc.subject_id for sc in track_config.subject_configs}
    effective_subjects = get_student_effective_subjects(student)
    effective_subject_ids = {s.id for s in effective_subjects}
    allowed_subject_ids = configured_subject_ids.intersection(effective_subject_ids)

    clean_rank = None
    if overall_rank is not None:
        try:
            clean_rank = int(overall_rank)
            if clean_rank <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise ExamValidationError("Overall rank must be a positive integer if provided.")

    seen_subjects: Set[uuid.UUID] = set()
    parsed_items = []
    for item in subject_data:
        sub_id = item.get("subject_id")
        if isinstance(sub_id, str):
            sub_id = uuid.UUID(sub_id)
        if not sub_id or sub_id not in allowed_subject_ids:
            sub = get_subject_by_id(db, sub_id) if sub_id else None
            sub_name = sub.name if sub else str(sub_id)
            raise ExamValidationError(
                f"Subject '{sub_name}' is not allowed for your track in this exam."
            )
        if sub_id in seen_subjects:
            raise ExamValidationError("Duplicate subject entry in submitted results.")
        seen_subjects.add(sub_id)

        try:
            correct = int(item.get("correct_answers", 0))
            incorrect = int(item.get("incorrect_answers", 0))
        except (ValueError, TypeError):
            raise ExamValidationError("Correct and incorrect answers must be valid integers.")

        if correct < 0 or incorrect < 0:
            raise ExamValidationError("Correct and incorrect counts must be non-negative integers.")

        try:
            percentage = float(item.get("percentage", 0.0))
        except (ValueError, TypeError):
            raise ExamValidationError("Percentage must be a valid number.")

        if percentage < 0.0 or percentage > 100.0:
            raise ExamValidationError("Percentage must be between 0 and 100.")

        parsed_items.append((sub_id, correct, incorrect, percentage))

    result.overall_rank = clean_rank
    result.notes = notes.strip() if notes and notes.strip() else None
    if report_card_file_path:
        result.report_card_file_path = report_card_file_path
        result.report_card_file_name = report_card_file_name

    # Remove existing subject results and recreate
    for sr in list(result.subject_results):
        db.delete(sr)
    db.flush()

    for sub_id, correct, incorrect, percentage in parsed_items:
        subject_result = StudentExamSubjectResult(
            student_exam_result_id=result.id,
            subject_id=sub_id,
            correct_answers=correct,
            incorrect_answers=incorrect,
            percentage=percentage,
        )
        db.add(subject_result)

    db.commit()
    return get_student_exam_result_by_id(db, result.id)


def get_student_exam_analytics(db: Session, student_id: uuid.UUID) -> Dict[str, Any]:
    """Calculate rich performance analytics for a student across all exam occurrences."""
    results = (
        db.query(StudentExamResult)
        .join(ExamSession, ExamSession.id == StudentExamResult.exam_session_id)
        .options(
            joinedload(StudentExamResult.exam_session).joinedload(ExamSession.exam),
            joinedload(StudentExamResult.subject_results).joinedload(StudentExamSubjectResult.subject),
        )
        .filter(StudentExamResult.student_id == student_id)
        .order_by(ExamSession.date.asc(), ExamSession.created_at.asc())
        .all()
    )

    if not results:
        return {
            "has_data": False,
            "results_count": 0,
            "subject_trends": {},
            "overall_trends": [],
            "subject_stats": {},
            "improving_declining": {"improving": [], "declining": [], "stable": []},
            "history": [],
        }

    # 1. Subject-by-subject trajectories
    subject_trends: Dict[str, Dict[str, Any]] = {}
    subject_scores: Dict[str, List[float]] = {}
    overall_trends: List[Dict[str, Any]] = []
    history: List[Dict[str, Any]] = []

    for r in results:
        sess = r.exam_session
        date_str = sess.date.strftime("%Y-%m-%d")
        exam_title = sess.title or sess.exam.title

        total_correct = 0
        total_incorrect = 0
        percentages = []

        sub_details = []
        for sr in r.subject_results:
            sub_name = sr.subject.name
            total_correct += sr.correct_answers
            total_incorrect += sr.incorrect_answers
            percentages.append(sr.percentage)

            if sub_name not in subject_trends:
                subject_trends[sub_name] = {
                    "subject_id": str(sr.subject_id),
                    "name": sub_name,
                    "points": [],
                }
                subject_scores[sub_name] = []

            subject_trends[sub_name]["points"].append({
                "date": date_str,
                "exam_title": exam_title,
                "percentage": sr.percentage,
                "correct": sr.correct_answers,
                "incorrect": sr.incorrect_answers,
            })
            subject_scores[sub_name].append(sr.percentage)

            sub_details.append({
                "subject_name": sub_name,
                "correct": sr.correct_answers,
                "incorrect": sr.incorrect_answers,
                "percentage": sr.percentage,
            })

        avg_pct = round(sum(percentages) / len(percentages), 2) if percentages else 0.0

        overall_trends.append({
            "date": date_str,
            "exam_title": exam_title,
            "average_percentage": avg_pct,
            "total_correct": total_correct,
            "total_incorrect": total_incorrect,
            "overall_rank": r.overall_rank,
        })

        history.append({
            "result_id": str(r.id),
            "session_id": str(sess.id),
            "exam_title": exam_title,
            "date": date_str,
            "overall_rank": r.overall_rank,
            "notes": r.notes,
            "average_percentage": avg_pct,
            "total_correct": total_correct,
            "total_incorrect": total_incorrect,
            "subjects": sub_details,
            "has_report_card": bool(r.report_card_file_path),
            "report_card_file_name": r.report_card_file_name,
        })

    # 2. Subject stats and improving/declining calculation
    subject_stats: Dict[str, Dict[str, Any]] = {}
    improving: List[Dict[str, Any]] = []
    declining: List[Dict[str, Any]] = []
    stable: List[Dict[str, Any]] = []

    for name, scores in subject_scores.items():
        avg_score = round(sum(scores) / len(scores), 2)
        latest = scores[-1]
        subject_stats[name] = {
            "name": name,
            "count": len(scores),
            "average": avg_score,
            "latest": latest,
            "min": min(scores),
            "max": max(scores),
        }
        if len(scores) >= 2:
            prev = scores[-2]
            delta = round(latest - prev, 2)
            item = {"name": name, "latest": latest, "previous": prev, "delta": delta}
            if delta > 0:
                improving.append(item)
            elif delta < 0:
                declining.append(item)
            else:
                stable.append(item)

    return {
        "has_data": True,
        "results_count": len(results),
        "subject_trends": subject_trends,
        "overall_trends": overall_trends,
        "subject_stats": subject_stats,
        "improving_declining": {
            "improving": improving,
            "declining": declining,
            "stable": stable,
        },
        "history": list(reversed(history)),
    }


def get_tutor_session_analytics(db: Session, session_id: uuid.UUID) -> Dict[str, Any]:
    """Analytics for a specific exam session comparing all students who took it."""
    session = get_exam_session_by_id(db, session_id)
    if not session:
        raise ExamSessionNotFoundError(f"Exam session with id {session_id} not found.")

    subject_totals: Dict[str, List[float]] = {}
    student_rows = []

    for r in session.results:
        sub_map = {}
        total_correct = 0
        total_incorrect = 0
        scores = []
        for sr in r.subject_results:
            name = sr.subject.name
            sub_map[name] = {
                "correct": sr.correct_answers,
                "incorrect": sr.incorrect_answers,
                "percentage": sr.percentage,
            }
            total_correct += sr.correct_answers
            total_incorrect += sr.incorrect_answers
            scores.append(sr.percentage)
            if name not in subject_totals:
                subject_totals[name] = []
            subject_totals[name].append(sr.percentage)

        avg_pct = round(sum(scores) / len(scores), 2) if scores else 0.0
        student_rows.append({
            "result_id": str(r.id),
            "student_id": str(r.student.id),
            "student_name": r.student.full_name,
            "overall_rank": r.overall_rank,
            "average_percentage": avg_pct,
            "total_correct": total_correct,
            "total_incorrect": total_incorrect,
            "subject_scores": sub_map,
            "has_report_card": bool(r.report_card_file_path),
            "report_card_file_name": r.report_card_file_name,
        })

    subject_averages = {
        name: round(sum(vals) / len(vals), 2)
        for name, vals in subject_totals.items()
    }

    # All unique subjects across track configs for table headers
    all_subjects = set()
    for tc in session.track_configs:
        for sc in tc.subject_configs:
            all_subjects.add(sc.subject.name)

    return {
        "session": session,
        "participant_count": len(session.results),
        "students": student_rows,
        "subject_averages": subject_averages,
        "all_subjects": sorted(list(all_subjects)),
    }


def get_tutor_student_analytics(db: Session, student_id: uuid.UUID) -> Dict[str, Any]:
    student = db.query(User).filter(User.id == student_id, User.role == "STUDENT").first()
    if not student:
        raise ExamValidationError(f"Student with id {student_id} not found.")
    analytics = get_student_exam_analytics(db, student_id)
    return {
        "student": student,
        "analytics": analytics,
    }


def assign_external_exam_to_students(
    db: Session,
    exam_session_id: uuid.UUID,
    student_ids: List[uuid.UUID],
) -> None:
    session = get_exam_session_by_id(db, exam_session_id)
    if not session:
        raise ExamSessionNotFoundError(f"Exam session with id {exam_session_id} not found.")

    for sid in student_ids:
        existing = db.query(ExternalExamAssignment).filter(
            ExternalExamAssignment.exam_session_id == session.id,
            ExternalExamAssignment.student_id == sid,
        ).first()
        if not existing:
            assignment = ExternalExamAssignment(exam_session_id=session.id, student_id=sid)
            db.add(assignment)
    db.commit()


def get_student_external_exams_in_date_range(
    db: Session,
    student: User,
    start_date: date,
    end_date: date,
) -> Dict[date, List[ExamSession]]:
    """
    Find assigned scheduled external exams that fall within a date range (for 14-day study plan integration).
    Returns mapping of date -> list of exam sessions.
    """
    if not student.academic_track_id:
        return {}

    query = (
        db.query(ExamSession)
        .options(
            joinedload(ExamSession.exam),
            joinedload(ExamSession.track_configs),
        )
        .filter(
            ExamSession.date >= start_date,
            ExamSession.date <= end_date,
        )
    )
    sessions = query.all()
    exams_by_date: Dict[date, List[ExamSession]] = {}

    for s in sessions:
        # Check track configuration or direct assignment
        is_in_track = any(tc.track_id == student.academic_track_id for tc in s.track_configs)
        has_direct_assignment = any(a.student_id == student.id for a in s.assignments)
        if is_in_track or has_direct_assignment:
            if s.date not in exams_by_date:
                exams_by_date[s.date] = []
            exams_by_date[s.date].append(s)

    return exams_by_date


def create_historical_exam_result(
    db: Session,
    student_id: uuid.UUID,
    exam_name: str,
    exam_date: date,
    subject_scores: List[Dict[str, Any]],
    grade: Optional[str] = None,
    academic_track_id: Optional[uuid.UUID] = None,
    overall_rank: Optional[int] = None,
    notes: Optional[str] = None,
    report_card_file_path: Optional[str] = None,
    report_card_file_name: Optional[str] = None,
) -> HistoricalExamResult:
    clean_name = (exam_name or "").strip()
    if not clean_name:
        raise ExamValidationError("Historical exam name cannot be empty.")

    student = db.query(User).filter(User.id == student_id, User.role == "STUDENT").first()
    if not student:
        raise ExamValidationError(f"Student with id {student_id} not found.")

    if not subject_scores:
        raise ExamValidationError("At least one subject percentage must be recorded.")

    clean_rank = None
    if overall_rank is not None:
        try:
            clean_rank = int(overall_rank)
            if clean_rank <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise ExamValidationError("Overall rank must be a positive integer if provided.")

    hist_result = HistoricalExamResult(
        student_id=student.id,
        exam_name=clean_name,
        exam_date=exam_date,
        grade=grade.strip() if grade else student.grade,
        academic_track_id=academic_track_id or student.academic_track_id,
        overall_rank=clean_rank,
        notes=notes.strip() if notes and notes.strip() else None,
        report_card_file_path=report_card_file_path,
        report_card_file_name=report_card_file_name,
    )
    db.add(hist_result)
    db.flush()

    for item in subject_scores:
        s_name = str(item.get("subject_name", "")).strip()
        if not s_name:
            continue
        try:
            pct = float(item.get("percentage", 0.0))
        except (ValueError, TypeError):
            raise ExamValidationError(f"Percentage for subject '{s_name}' must be a valid number.")

        if pct < 0.0 or pct > 100.0:
            raise ExamValidationError(f"Percentage for subject '{s_name}' must be between 0 and 100.")

        sub_rec = HistoricalExamSubjectResult(
            historical_exam_result_id=hist_result.id,
            subject_name=s_name,
            percentage=pct,
        )
        db.add(sub_rec)

    db.commit()
    db.refresh(hist_result)
    return hist_result


def list_historical_exam_results(
    db: Session,
    student_id: Optional[uuid.UUID] = None,
) -> List[HistoricalExamResult]:
    query = (
        db.query(HistoricalExamResult)
        .options(
            joinedload(HistoricalExamResult.student),
            joinedload(HistoricalExamResult.academic_track),
            joinedload(HistoricalExamResult.subject_results),
        )
    )
    if student_id:
        query = query.filter(HistoricalExamResult.student_id == student_id)
    return query.order_by(desc(HistoricalExamResult.exam_date)).all()


def get_historical_exam_result_by_id(
    db: Session,
    result_id: uuid.UUID,
) -> Optional[HistoricalExamResult]:
    return (
        db.query(HistoricalExamResult)
        .options(
            joinedload(HistoricalExamResult.student),
            joinedload(HistoricalExamResult.academic_track),
            joinedload(HistoricalExamResult.subject_results),
        )
        .filter(HistoricalExamResult.id == result_id)
        .first()
    )
