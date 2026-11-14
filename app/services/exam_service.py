import json
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy import desc
from sqlalchemy.orm import Session, joinedload

from app.core.timezone import now_utc
from app.models.exam import (
    Exam,
    ExamGradeTrackConfig,
    ExamReportingGroup,
    ExamReportingGroupSubject,
    ExamSeriesAssignment,
    ExamSession,
    ExamSessionAudit,
    ExamSubjectConfiguration,
    ExamTrackConfiguration,
    HistoricalExamResult,
    HistoricalExamSubjectResult,
    StudentExamGroupResult,
    StudentExamResult,
    StudentExamSubjectResult,
    ExternalExamAssignment,
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


class IneligibleStudentError(ExamValidationError):
    pass


class ExamResultNotFoundError(Exception):
    pass


class DuplicateExamResultError(Exception):
    pass


WEEKDAY_MAPPING: Dict[int, Dict[str, Any]] = {
    0: {"name_fa": "شنبه", "name_en": "Saturday", "py_weekday": 5},
    1: {"name_fa": "یکشنبه", "name_en": "Sunday", "py_weekday": 6},
    2: {"name_fa": "دوشنبه", "name_en": "Monday", "py_weekday": 0},
    3: {"name_fa": "سه‌شنبه", "name_en": "Tuesday", "py_weekday": 1},
    4: {"name_fa": "چهارشنبه", "name_en": "Wednesday", "py_weekday": 2},
    5: {"name_fa": "پنج‌شنبه", "name_en": "Thursday", "py_weekday": 3},
    6: {"name_fa": "جمعه", "name_en": "Friday", "py_weekday": 4},
}


def calculate_recurring_dates(
    first_exam_date: date,
    last_exam_date: date,
    interval_weeks: int,
    weekday: Optional[int] = None,
) -> List[date]:
    """
    Generate recurring exam dates anchored to first_exam_date.
    Each subsequent date is strictly (first_date + 7 * interval_weeks * k) days.
    """
    if interval_weeks < 1:
        raise ExamValidationError("Recurrence interval must be at least 1 week.")
    if first_exam_date > last_exam_date:
        raise ExamValidationError("First exam date cannot be after last exam date.")

    anchor_date = first_exam_date
    if weekday is not None and weekday in WEEKDAY_MAPPING:
        target_py = WEEKDAY_MAPPING[weekday]["py_weekday"]
        days_ahead = (target_py - anchor_date.weekday()) % 7
        anchor_date = anchor_date + timedelta(days=days_ahead)
        if anchor_date > last_exam_date:
            return []

    dates: List[date] = []
    step = timedelta(days=7 * interval_weeks)
    current = anchor_date
    while current <= last_exam_date:
        dates.append(current)
        current += step

    return dates


def preview_recurring_schedule(
    first_exam_date: date,
    last_exam_date: date,
    interval_weeks: int,
    weekday: Optional[int] = None,
) -> Dict[str, Any]:
    """Generate preview of occurrences before saving schedule."""
    dates = calculate_recurring_dates(first_exam_date, last_exam_date, interval_weeks, weekday)
    occurrences = []
    for idx, d in enumerate(dates):
        py_wd = d.weekday()
        wd_info = next((v for v in WEEKDAY_MAPPING.values() if v["py_weekday"] == py_wd), None)
        occurrences.append({
            "sequence_order": idx + 1,
            "date": d,
            "date_iso": d.isoformat(),
            "weekday_name_fa": wd_info["name_fa"] if wd_info else "",
            "weekday_name_en": wd_info["name_en"] if wd_info else "",
        })
    return {
        "total_occurrences": len(occurrences),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "occurrences": occurrences,
    }


def create_exam(
    db: Session,
    title: str,
    description: Optional[str] = None,
    first_exam_date: Optional[date] = None,
    last_exam_date: Optional[date] = None,
    recurrence_interval_weeks: Optional[int] = None,
    recurrence_weekday: Optional[int] = None,
) -> Exam:
    clean_title = (title or "").strip()
    if not clean_title:
        raise ExamValidationError("Exam title cannot be empty.")

    if recurrence_interval_weeks is not None and recurrence_interval_weeks < 1:
        raise ExamValidationError("Recurrence interval must be at least 1 week.")
    if first_exam_date and last_exam_date and first_exam_date > last_exam_date:
        raise ExamValidationError("First exam date cannot be after last exam date.")

    exam = Exam(
        title=clean_title,
        description=description.strip() if description and description.strip() else None,
        first_exam_date=first_exam_date,
        last_exam_date=last_exam_date,
        recurrence_interval_weeks=recurrence_interval_weeks,
        recurrence_weekday=recurrence_weekday,
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
    first_exam_date: Optional[date] = None,
    last_exam_date: Optional[date] = None,
    recurrence_interval_weeks: Optional[int] = None,
    recurrence_weekday: Optional[int] = None,
) -> Exam:
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")

    clean_title = (title or "").strip()
    if not clean_title:
        raise ExamValidationError("Exam title cannot be empty.")

    if recurrence_interval_weeks is not None and recurrence_interval_weeks < 1:
        raise ExamValidationError("Recurrence interval must be at least 1 week.")
    if first_exam_date and last_exam_date and first_exam_date > last_exam_date:
        raise ExamValidationError("First exam date cannot be after last exam date.")

    exam.title = clean_title
    exam.description = description.strip() if description and description.strip() else None
    if is_active is not None:
        exam.is_active = is_active
    if first_exam_date is not None:
        exam.first_exam_date = first_exam_date
    if last_exam_date is not None:
        exam.last_exam_date = last_exam_date
    if recurrence_interval_weeks is not None:
        exam.recurrence_interval_weeks = recurrence_interval_weeks
    if recurrence_weekday is not None:
        exam.recurrence_weekday = recurrence_weekday

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
    return (
        db.query(Exam)
        .options(
            joinedload(Exam.grade_track_configs).joinedload(ExamGradeTrackConfig.track),
            joinedload(Exam.grade_track_configs)
            .joinedload(ExamGradeTrackConfig.reporting_groups)
            .joinedload(ExamReportingGroup.subjects),
            joinedload(Exam.sessions),
            joinedload(Exam.series_assignments).joinedload(ExamSeriesAssignment.student),
        )
        .filter(Exam.id == exam_id)
        .first()
    )


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
            joinedload(ExamSession.results)
            .joinedload(StudentExamResult.group_results),
            joinedload(ExamSession.assignments)
            .joinedload(ExternalExamAssignment.student),
            joinedload(ExamSession.audit_logs)
            .joinedload(ExamSessionAudit.actor),
            joinedload(ExamSession.reporting_groups)
            .joinedload(ExamReportingGroup.subjects),
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


def configure_exam_grade_track(
    db: Session,
    exam_id: uuid.UUID,
    grade: str,
    track_id: uuid.UUID,
    reporting_groups_data: List[Dict[str, Any]],
) -> ExamGradeTrackConfig:
    """Configure reporting groups and subject combinations for an eligible grade/track."""
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")

    clean_grade = (grade or "").strip()
    if not clean_grade:
        raise ExamValidationError("Grade cannot be empty.")

    track = get_track_by_id(db, track_id)
    if not track:
        raise ExamValidationError(f"Academic track with id {track_id} not found.")

    if not reporting_groups_data:
        raise ExamValidationError("At least one reporting group must be configured.")

    track_subject_ids = {s.id for s in track.subjects}

    for grp in reporting_groups_data:
        grp_title = (grp.get("title") or "").strip()
        if not grp_title:
            raise ExamValidationError("Reporting group title cannot be empty.")
        s_ids = list(dict.fromkeys(grp.get("subject_ids") or []))
        for sid in s_ids:
            if isinstance(sid, str):
                sid = uuid.UUID(sid)
            if sid not in track_subject_ids:
                sub = get_subject_by_id(db, sid)
                sub_name = sub.name if sub else str(sid)
                raise ExamValidationError(f"Subject '{sub_name}' does not belong to track '{track.name}'.")

    config = db.query(ExamGradeTrackConfig).filter(
        ExamGradeTrackConfig.exam_id == exam.id,
        ExamGradeTrackConfig.grade == clean_grade,
        ExamGradeTrackConfig.track_id == track.id,
    ).first()

    if not config:
        config = ExamGradeTrackConfig(
            exam_id=exam.id,
            grade=clean_grade,
            track_id=track.id,
        )
        db.add(config)
        db.flush()
    else:
        for rg in list(config.reporting_groups):
            db.delete(rg)
        db.flush()

    for idx, grp in enumerate(reporting_groups_data):
        grp_title = (grp.get("title") or "").strip()
        order_idx = int(grp.get("order_index", idx))
        s_ids = [uuid.UUID(str(sid)) for sid in (grp.get("subject_ids") or [])]
        subjects = [s for s in track.subjects if s.id in s_ids]

        rep_group = ExamReportingGroup(
            exam_grade_track_config_id=config.id,
            title=grp_title,
            order_index=order_idx,
            subjects=subjects,
        )
        db.add(rep_group)

    db.commit()
    db.refresh(config)
    return config


def get_exam_grade_track_config(db: Session, config_id: uuid.UUID) -> Optional[ExamGradeTrackConfig]:
    return (
        db.query(ExamGradeTrackConfig)
        .options(
            joinedload(ExamGradeTrackConfig.track),
            joinedload(ExamGradeTrackConfig.reporting_groups)
            .joinedload(ExamReportingGroup.subjects),
        )
        .filter(ExamGradeTrackConfig.id == config_id)
        .first()
    )


def list_exam_grade_track_configs(db: Session, exam_id: uuid.UUID) -> List[ExamGradeTrackConfig]:
    return (
        db.query(ExamGradeTrackConfig)
        .options(
            joinedload(ExamGradeTrackConfig.track),
            joinedload(ExamGradeTrackConfig.reporting_groups)
            .joinedload(ExamReportingGroup.subjects),
        )
        .filter(ExamGradeTrackConfig.exam_id == exam_id)
        .order_by(ExamGradeTrackConfig.grade.asc())
        .all()
    )


def delete_exam_grade_track_config(db: Session, config_id: uuid.UUID) -> None:
    config = db.query(ExamGradeTrackConfig).filter(ExamGradeTrackConfig.id == config_id).first()
    if config:
        db.delete(config)
        db.commit()


def create_exam_session(
    db: Session,
    exam_id: uuid.UUID,
    exam_date: date,
    title: Optional[str] = None,
    track_subjects_map: Optional[Dict[uuid.UUID, List[uuid.UUID]]] = None,
    status: str = "SCHEDULED",
    is_manually_added: bool = False,
    sequence_order: Optional[int] = None,
) -> ExamSession:
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    if not exam.is_active:
        raise ExamValidationError(f"Cannot schedule session for archived exam '{exam.title}'.")

    existing = db.query(ExamSession).filter(
        ExamSession.exam_id == exam.id,
        ExamSession.date == exam_date,
    ).first()
    if existing:
        raise ExamValidationError(f"An occurrence for exam '{exam.title}' on {exam_date} already exists.")

    if track_subjects_map is None and exam.grade_track_configs:
        track_subjects_map = {}
        for gtc in exam.grade_track_configs:
            if gtc.track_id not in track_subjects_map:
                track_subjects_map[gtc.track_id] = []
            for rg in gtc.reporting_groups:
                for sub in rg.subjects:
                    if sub.id not in track_subjects_map[gtc.track_id]:
                        track_subjects_map[gtc.track_id].append(sub.id)

    if not track_subjects_map or len(track_subjects_map) == 0:
        raise ExamValidationError("At least one academic track must be configured for the exam.")

    session = ExamSession(
        exam_id=exam.id,
        date=exam_date,
        title=title.strip() if title and title.strip() else None,
        status=status,
        is_manually_added=is_manually_added,
        sequence_order=sequence_order,
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

    for sa in exam.series_assignments:
        existing_ass = db.query(ExternalExamAssignment).filter(
            ExternalExamAssignment.exam_session_id == session.id,
            ExternalExamAssignment.student_id == sa.student_id,
        ).first()
        if not existing_ass:
            db.add(ExternalExamAssignment(exam_session_id=session.id, student_id=sa.student_id))

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

    for sa in exam.series_assignments:
        existing_ass = db.query(ExternalExamAssignment).filter(
            ExternalExamAssignment.exam_session_id == session.id,
            ExternalExamAssignment.student_id == sa.student_id,
        ).first()
        if not existing_ass:
            db.add(ExternalExamAssignment(exam_session_id=session.id, student_id=sa.student_id))

    db.commit()
    db.refresh(session)
    return get_exam_session_by_id(db, session.id)


def delete_exam_session(db: Session, session_id: uuid.UUID) -> None:
    session = get_exam_session_by_id(db, session_id)
    if not session:
        raise ExamSessionNotFoundError(f"Exam session with id {session_id} not found.")
    db.delete(session)
    db.commit()


def generate_series_sessions(
    db: Session,
    exam_id: uuid.UUID,
    dates: Optional[List[date]] = None,
    actor_id: Optional[uuid.UUID] = None,
) -> List[ExamSession]:
    """Generate all scheduled occurrences for an exam series, preventing duplicates."""
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")

    if dates is None:
        if not exam.first_exam_date or not exam.last_exam_date or not exam.recurrence_interval_weeks:
            raise ExamValidationError("Exam series does not have complete recurrence configuration.")
        dates = calculate_recurring_dates(
            first_exam_date=exam.first_exam_date,
            last_exam_date=exam.last_exam_date,
            interval_weeks=exam.recurrence_interval_weeks,
            weekday=exam.recurrence_weekday,
        )

    if not dates:
        raise ExamValidationError("No matching exam dates to generate.")

    created_sessions: List[ExamSession] = []
    existing_dates = {s.date for s in exam.sessions}

    for idx, d in enumerate(dates):
        if d in existing_dates:
            continue
        session = create_exam_session(
            db,
            exam_id=exam.id,
            exam_date=d,
            sequence_order=idx + 1,
            status="SCHEDULED",
            is_manually_added=False,
        )
        audit = ExamSessionAudit(
            exam_session_id=session.id,
            actor_id=actor_id,
            action="CREATED",
            reason="Schedule generation",
        )
        db.add(audit)
        created_sessions.append(session)

    db.commit()
    return created_sessions


def skip_exam_session(
    db: Session,
    session_id: uuid.UUID,
    actor_id: Optional[uuid.UUID] = None,
    reason: Optional[str] = None,
    force_if_results: bool = False,
) -> ExamSession:
    """Mark an occurrence as No Exam (skipped) without shifting later dates."""
    session = get_exam_session_by_id(db, session_id)
    if not session:
        raise ExamSessionNotFoundError(f"Exam session with id {session_id} not found.")

    if session.results and len(session.results) > 0 and not force_if_results:
        raise ExamValidationError("This occurrence already has submitted results. Confirmation required before skipping.")

    session.status = "SKIPPED"
    session.skip_reason = reason.strip() if reason and reason.strip() else None

    audit = ExamSessionAudit(
        exam_session_id=session.id,
        actor_id=actor_id,
        action="SKIPPED",
        reason=reason.strip() if reason and reason.strip() else None,
    )
    db.add(audit)
    db.commit()
    db.refresh(session)
    return session


def restore_exam_session(
    db: Session,
    session_id: uuid.UUID,
    actor_id: Optional[uuid.UUID] = None,
    reason: Optional[str] = None,
) -> ExamSession:
    """Restore a previously skipped occurrence back to SCHEDULED."""
    session = get_exam_session_by_id(db, session_id)
    if not session:
        raise ExamSessionNotFoundError(f"Exam session with id {session_id} not found.")

    session.status = "SCHEDULED"
    session.skip_reason = None

    audit = ExamSessionAudit(
        exam_session_id=session.id,
        actor_id=actor_id,
        action="RESTORED",
        reason=reason.strip() if reason and reason.strip() else None,
    )
    db.add(audit)
    db.commit()
    db.refresh(session)
    return session


def add_manual_replacement_session(
    db: Session,
    exam_id: uuid.UUID,
    exam_date: date,
    title: Optional[str] = None,
    actor_id: Optional[uuid.UUID] = None,
) -> ExamSession:
    """Add a replacement exam occurrence manually."""
    session = create_exam_session(
        db,
        exam_id=exam_id,
        exam_date=exam_date,
        title=title,
        status="SCHEDULED",
        is_manually_added=True,
    )
    audit = ExamSessionAudit(
        exam_session_id=session.id,
        actor_id=actor_id,
        action="MANUAL_ADDED",
        reason="Manual replacement occurrence",
    )
    db.add(audit)
    db.commit()
    return session


def update_future_recurrence(
    db: Session,
    exam_id: uuid.UUID,
    new_interval_weeks: int,
    new_first_date: date,
    new_last_date: date,
    new_weekday: Optional[int] = None,
    actor_id: Optional[uuid.UUID] = None,
) -> List[ExamSession]:
    """
    Update recurrence rules for future occurrences while strictly preserving completed/submitted occurrences.
    """
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")

    exam.recurrence_interval_weeks = new_interval_weeks
    exam.first_exam_date = new_first_date
    exam.last_exam_date = new_last_date
    exam.recurrence_weekday = new_weekday

    today = date.today()
    # Find cutoff: any session in past OR having results must be preserved
    preserved_dates = set()
    for s in list(exam.sessions):
        has_results = len(s.results) > 0
        is_past = s.date < today
        if has_results or is_past:
            preserved_dates.add(s.date)
        else:
            db.delete(s)
    db.flush()

    new_dates = calculate_recurring_dates(
        first_exam_date=new_first_date,
        last_exam_date=new_last_date,
        interval_weeks=new_interval_weeks,
        weekday=new_weekday,
    )

    created = []
    for idx, d in enumerate(new_dates):
        if d in preserved_dates:
            continue
        session = create_exam_session(
            db,
            exam_id=exam.id,
            exam_date=d,
            sequence_order=idx + 1,
            status="SCHEDULED",
            is_manually_added=False,
        )
        audit = ExamSessionAudit(
            exam_session_id=session.id,
            actor_id=actor_id,
            action="RESCHEDULED",
            reason="Recurrence updated",
        )
        db.add(audit)
        created.append(session)

    db.commit()
    return created


def get_student_available_exams(db: Session, student: User) -> Dict[str, Any]:
    if not student.academic_track_id:
        return {"upcoming": [], "past": [], "track_assigned": False}

    assigned_series_ids = {
        sa.exam_id for sa in db.query(ExamSeriesAssignment).filter(ExamSeriesAssignment.student_id == student.id).all()
    }
    assigned_session_ids = {
        ea.exam_session_id for ea in db.query(ExternalExamAssignment).filter(ExternalExamAssignment.student_id == student.id).all()
    }
    result_session_ids = {
        sr.exam_session_id for sr in db.query(StudentExamResult).filter(StudentExamResult.student_id == student.id).all()
    }

    all_sessions = (
        db.query(ExamSession)
        .options(
            joinedload(ExamSession.exam),
            joinedload(ExamSession.track_configs)
            .joinedload(ExamTrackConfiguration.subject_configs)
            .joinedload(ExamSubjectConfiguration.subject),
            joinedload(ExamSession.results)
            .joinedload(StudentExamResult.subject_results),
            joinedload(ExamSession.results)
            .joinedload(StudentExamResult.group_results),
        )
        .order_by(desc(ExamSession.date))
        .all()
    )

    today = date.today()
    upcoming = []
    past = []

    for s in all_sessions:
        is_assigned = (
            s.id in assigned_session_ids
            or s.exam_id in assigned_series_ids
            or any(tc.track_id == student.academic_track_id for tc in s.track_configs)
        )
        has_result = s.id in result_session_ids
        if not is_assigned and not has_result:
            continue

        student_result = next((r for r in s.results if r.student_id == student.id), None)
        item = {
            "session": s,
            "result": student_result,
            "has_submitted": student_result is not None,
            "status": s.status,
        }

        # Skipped and cancelled occurrences must NOT appear as active upcoming exams
        if s.status in ("SKIPPED", "CANCELLED") and not student_result:
            continue

        if s.date >= today and student_result is None and s.status == "SCHEDULED":
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
    subject_data: Optional[List[Dict[str, Any]]] = None,
    group_data: Optional[List[Dict[str, Any]]] = None,
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

    if session.status in ("SKIPPED", "CANCELLED"):
        raise ExamValidationError("Cannot submit results for a skipped or cancelled exam occurrence.")

    existing_result = get_student_exam_result(db, student.id, session.id)
    if existing_result:
        raise DuplicateExamResultError("Results have already been submitted for this exam occurrence.")

    track_config = next(
        (tc for tc in session.track_configs if tc.track_id == student.academic_track_id),
        None,
    )
    if not track_config and not session.exam.grade_track_configs:
        raise ExamValidationError("This exam is not available for your academic track.")

    grade_track_cfg = get_student_series_grade_track_config(db, session.exam_id, student)

    if not group_data and not subject_data:
        raise ExamValidationError("At least one subject or group result must be submitted.")

    clean_rank = None
    if overall_rank is not None:
        try:
            clean_rank = int(overall_rank)
            if clean_rank <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise ExamValidationError("Overall rank must be a positive integer if provided.")

    snapshot_data = None
    if grade_track_cfg:
        snapshot_data = {
            "grade": student.grade,
            "academic_track_id": str(student.academic_track_id),
            "track_name": student.academic_track.name if student.academic_track else "",
            "reporting_groups": [
                {
                    "id": str(rg.id),
                    "title": rg.title,
                    "order_index": rg.order_index,
                    "subjects": [{"id": str(s.id), "name": s.name} for s in rg.subjects],
                }
                for rg in grade_track_cfg.reporting_groups
            ],
        }

    parsed_group_items = []
    if group_data:
        for grp in group_data:
            g_title = (grp.get("group_title") or grp.get("title") or "").strip()
            if not g_title:
                raise ExamValidationError("Reporting group title cannot be empty.")
            try:
                pct = float(grp.get("percentage", 0.0))
            except (ValueError, TypeError):
                raise ExamValidationError("Percentage must be a valid number.")
            if pct < 0.0 or pct > 100.0:
                raise ExamValidationError("Percentage must be between 0 and 100.")
            rg_id = grp.get("reporting_group_id")
            if isinstance(rg_id, str):
                rg_id = uuid.UUID(rg_id)

            parsed_group_items.append((rg_id, g_title, pct, grp.get("included_subject_names")))

    parsed_subject_items = []
    if subject_data:
        configured_subject_ids = {sc.subject_id for sc in track_config.subject_configs} if track_config else set()
        effective_subjects = get_student_effective_subjects(student)
        effective_subject_ids = {s.id for s in effective_subjects}
        allowed_subject_ids = configured_subject_ids.intersection(effective_subject_ids) if configured_subject_ids else effective_subject_ids

        seen_subjects: Set[uuid.UUID] = set()
        for item in subject_data:
            sub_id = item.get("subject_id")
            if isinstance(sub_id, str):
                sub_id = uuid.UUID(sub_id)
            if not sub_id or (allowed_subject_ids and sub_id not in allowed_subject_ids):
                sub = get_subject_by_id(db, sub_id) if sub_id else None
                sub_name = sub.name if sub else str(sub_id)
                raise ExamValidationError(f"Subject '{sub_name}' is not allowed for your track in this exam.")
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

            parsed_subject_items.append((sub_id, correct, incorrect, percentage))

    result = StudentExamResult(
        student_id=student.id,
        exam_session_id=session.id,
        overall_rank=clean_rank,
        notes=notes.strip() if notes and notes.strip() else None,
        report_card_file_path=report_card_file_path,
        report_card_file_name=report_card_file_name,
        grade=student.grade,
        academic_track_id=student.academic_track_id,
        config_snapshot=json.dumps(snapshot_data, ensure_ascii=False) if snapshot_data else None,
    )
    db.add(result)
    db.flush()

    for rg_id, g_title, pct, inc_names in parsed_group_items:
        group_res = StudentExamGroupResult(
            student_exam_result_id=result.id,
            reporting_group_id=rg_id,
            group_title=g_title,
            percentage=pct,
            included_subject_names=inc_names,
        )
        db.add(group_res)

    for sub_id, correct, incorrect, percentage in parsed_subject_items:
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
    subject_data: Optional[List[Dict[str, Any]]] = None,
    group_data: Optional[List[Dict[str, Any]]] = None,
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

    clean_rank = None
    if overall_rank is not None:
        try:
            clean_rank = int(overall_rank)
            if clean_rank <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise ExamValidationError("Overall rank must be a positive integer if provided.")

    result.overall_rank = clean_rank
    result.notes = notes.strip() if notes and notes.strip() else None
    if report_card_file_path:
        result.report_card_file_path = report_card_file_path
        result.report_card_file_name = report_card_file_name

    if group_data is not None:
        for gr in list(result.group_results):
            db.delete(gr)
        db.flush()
        for grp in group_data:
            g_title = (grp.get("group_title") or grp.get("title") or "").strip()
            pct = float(grp.get("percentage", 0.0))
            if pct < 0.0 or pct > 100.0:
                raise ExamValidationError("Percentage must be between 0 and 100.")
            rg_id = grp.get("reporting_group_id")
            if isinstance(rg_id, str):
                rg_id = uuid.UUID(rg_id)
            group_res = StudentExamGroupResult(
                student_exam_result_id=result.id,
                reporting_group_id=rg_id,
                group_title=g_title,
                percentage=pct,
                included_subject_names=grp.get("included_subject_names"),
            )
            db.add(group_res)

    if subject_data is not None:
        for sr in list(result.subject_results):
            db.delete(sr)
        db.flush()
        for item in subject_data:
            sub_id = item.get("subject_id")
            if isinstance(sub_id, str):
                sub_id = uuid.UUID(sub_id)
            correct = int(item.get("correct_answers", 0))
            incorrect = int(item.get("incorrect_answers", 0))
            percentage = float(item.get("percentage", 0.0))
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


def get_student_series_grade_track_config(
    db: Session,
    exam_id: uuid.UUID,
    student: User,
) -> Optional[ExamGradeTrackConfig]:
    """Identify the matching reporting structure config for a student's grade and track."""
    if not student.grade or not student.academic_track_id:
        return None

    return (
        db.query(ExamGradeTrackConfig)
        .options(
            joinedload(ExamGradeTrackConfig.reporting_groups)
            .joinedload(ExamReportingGroup.subjects)
        )
        .filter(
            ExamGradeTrackConfig.exam_id == exam_id,
            ExamGradeTrackConfig.grade == str(student.grade),
            ExamGradeTrackConfig.track_id == student.academic_track_id,
        )
        .first()
    )


def evaluate_students_eligibility(
    db: Session,
    exam_id: uuid.UUID,
    student_ids: List[uuid.UUID],
) -> Dict[str, Any]:
    """Validate each student's eligibility independently and return breakdown."""
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")

    eligible: List[Dict[str, Any]] = []
    ineligible: List[Dict[str, Any]] = []

    for sid in student_ids:
        student = db.query(User).filter(User.id == sid, User.role == "STUDENT").first()
        if not student:
            ineligible.append({"student_id": sid, "student": None, "reason": "Student not found."})
            continue

        if not student.grade:
            ineligible.append({
                "student_id": sid,
                "student": student,
                "reason": "Student has no grade assigned in academic profile.",
            })
            continue

        if not student.academic_track_id:
            ineligible.append({
                "student_id": sid,
                "student": student,
                "reason": "Student has no academic track assigned.",
            })
            continue

        config = get_student_series_grade_track_config(db, exam_id, student)
        if not config:
            track_name = student.academic_track.name if student.academic_track else str(student.academic_track_id)
            ineligible.append({
                "student_id": sid,
                "student": student,
                "reason": f"Grade {student.grade} and track '{track_name}' combination is not eligible for this exam series.",
            })
            continue

        eligible.append({
            "student_id": sid,
            "student": student,
            "config": config,
            "reporting_groups": config.reporting_groups,
        })

    return {"eligible": eligible, "ineligible": ineligible}


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


def assign_exam_series_to_students(
    db: Session,
    exam_id: uuid.UUID,
    student_ids: List[uuid.UUID],
) -> Dict[str, Any]:
    """Assign an entire exam series to students, strictly rejecting ineligible students."""
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")

    eval_result = evaluate_students_eligibility(db, exam_id, student_ids)
    if eval_result["ineligible"]:
        reasons = "; ".join(f"Student {item.get('student').full_name if item.get('student') else item['student_id']}: {item['reason']}" for item in eval_result["ineligible"])
        raise IneligibleStudentError(f"Cannot assign series to incompatible students: {reasons}")

    assigned_count = 0
    for item in eval_result["eligible"]:
        st = item["student"]
        existing = db.query(ExamSeriesAssignment).filter(
            ExamSeriesAssignment.exam_id == exam.id,
            ExamSeriesAssignment.student_id == st.id,
        ).first()
        if not existing:
            sa = ExamSeriesAssignment(exam_id=exam.id, student_id=st.id)
            db.add(sa)
            assigned_count += 1

        for sess in exam.sessions:
            if sess.status == "SCHEDULED":
                existing_ea = db.query(ExternalExamAssignment).filter(
                    ExternalExamAssignment.exam_session_id == sess.id,
                    ExternalExamAssignment.student_id == st.id,
                ).first()
                if not existing_ea:
                    db.add(ExternalExamAssignment(exam_session_id=sess.id, student_id=st.id))

    db.commit()
    return {"assigned_count": assigned_count, "eligible_count": len(eval_result["eligible"])}


def check_student_series_eligibility(
    db: Session,
    student_id: uuid.UUID,
) -> List[Dict[str, Any]]:
    """
    Check if a student is still eligible for their assigned series following academic profile changes.
    Returns list of incompatible series assignments.
    """
    student = db.query(User).filter(User.id == student_id, User.role == "STUDENT").first()
    if not student:
        return []

    assignments = db.query(ExamSeriesAssignment).options(joinedload(ExamSeriesAssignment.exam)).filter(
        ExamSeriesAssignment.student_id == student.id
    ).all()

    incompatible = []
    for sa in assignments:
        config = get_student_series_grade_track_config(db, sa.exam_id, student)
        if not config:
            track_name = student.academic_track.name if student.academic_track else str(student.academic_track_id)
            incompatible.append({
                "assignment_id": str(sa.id),
                "exam_id": str(sa.exam_id),
                "exam_title": sa.exam.title,
                "current_grade": student.grade,
                "current_track": track_name,
                "reason": f"Student profile ({student.grade}, {track_name}) is no longer configured in series '{sa.exam.title}'.",
            })

    return incompatible


def get_all_series_incompatible_students(db: Session) -> List[Dict[str, Any]]:
    assignments = (
        db.query(ExamSeriesAssignment)
        .options(
            joinedload(ExamSeriesAssignment.exam),
            joinedload(ExamSeriesAssignment.student).joinedload(User.academic_track),
        )
        .all()
    )
    incompatible = []
    for sa in assignments:
        student = sa.student
        if not student:
            continue
        config = get_student_series_grade_track_config(db, sa.exam_id, student)
        if not config:
            track_name = student.academic_track.name if student.academic_track else str(student.academic_track_id)
            incompatible.append({
                "assignment_id": str(sa.id),
                "exam_id": str(sa.exam_id),
                "exam_title": sa.exam.title if sa.exam else "Unknown Series",
                "student_id": str(student.id),
                "student_name": student.full_name or student.username,
                "current_grade": student.grade,
                "current_track": track_name,
                "reason": f"Student '{student.full_name or student.username}' ({student.grade}, {track_name}) is no longer configured in series '{sa.exam.title if sa.exam else ''}'.",
            })
    return incompatible


def dismiss_series_incompatible_assignment(db: Session, assignment_id: uuid.UUID) -> None:
    sa = db.query(ExamSeriesAssignment).filter(ExamSeriesAssignment.id == assignment_id).first()
    if not sa:
        return
    exam_id = sa.exam_id
    student_id = sa.student_id

    db.delete(sa)

    sessions = db.query(ExamSession).filter(ExamSession.exam_id == exam_id).all()
    session_ids = [s.id for s in sessions]

    submitted_session_ids = {
        sr.exam_session_id
        for sr in db.query(StudentExamResult).filter(
            StudentExamResult.student_id == student_id,
            StudentExamResult.exam_session_id.in_(session_ids)
        ).all()
    }

    if session_ids:
        unsubmitted_assignments = db.query(ExternalExamAssignment).filter(
            ExternalExamAssignment.student_id == student_id,
            ExternalExamAssignment.exam_session_id.in_(session_ids),
        ).all()
        for u_ass in unsubmitted_assignments:
            if u_ass.exam_session_id not in submitted_session_ids:
                db.delete(u_ass)

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
            joinedload(ExamSession.exam).joinedload(Exam.series_assignments),
            joinedload(ExamSession.track_configs),
            joinedload(ExamSession.assignments),
        )
        .filter(
            ExamSession.date >= start_date,
            ExamSession.date <= end_date,
            ExamSession.status == "SCHEDULED",
        )
    )
    sessions = query.all()
    exams_by_date: Dict[date, List[ExamSession]] = {}

    for s in sessions:
        # Check direct assignment or series assignment
        has_direct_assignment = any(a.student_id == student.id for a in s.assignments)
        has_series_assignment = any(sa.student_id == student.id for sa in s.exam.series_assignments)
        is_in_track = any(tc.track_id == student.academic_track_id for tc in s.track_configs) if s.track_configs else True

        if is_in_track or has_direct_assignment or has_series_assignment:
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
