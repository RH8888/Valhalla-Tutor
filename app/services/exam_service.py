import json
import math
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.timezone import now_utc, today_local
from app.models.exam import (
    Exam,
    ExamGradeTrackConfig,
    ExamReportingGroup,
    ExamReportingGroupSubject,
    ExamSeriesAssignment,
    ExamSession,
    ExamSessionAudit,
    ExamAuditLog,
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


def _validate_percentage(raw_val: Any, subject_label: Optional[str] = None) -> float:
    """Parse and validate a finite exam percentage within [0.0, 100.0]."""
    prefix = f"Percentage for subject '{subject_label}'" if subject_label else "Percentage"
    try:
        pct = float(raw_val)
    except (ValueError, TypeError):
        raise ExamValidationError(f"{prefix} must be a valid number.")
    if not math.isfinite(pct) or pct < 0.0 or pct > 100.0:
        raise ExamValidationError(f"{prefix} must be between 0 and 100.")
    return pct


def _lock_exam_row(db: Session, exam_id: uuid.UUID, share: bool = False) -> Optional[uuid.UUID]:
    row = (
        db.query(Exam.id)
        .filter(Exam.id == exam_id)
        .with_for_update(read=share)
        .first()
    )
    return row[0] if row else None


def _lock_session_row(db: Session, session_id: uuid.UUID, share: bool = False) -> Optional[uuid.UUID]:
    if not session_id:
        return None
    parent_row = db.query(ExamSession.exam_id).filter(ExamSession.id == session_id).first()
    if not parent_row:
        return None
    _lock_exam_row(db, parent_row[0], share=True)
    row = (
        db.query(ExamSession.id)
        .filter(ExamSession.id == session_id)
        .with_for_update(read=share)
        .first()
    )
    return row[0] if row else None


def _lock_result_row(db: Session, result_id: uuid.UUID) -> Optional[uuid.UUID]:
    row = (
        db.query(StudentExamResult.id)
        .filter(StudentExamResult.id == result_id)
        .with_for_update()
        .first()
    )
    return row[0] if row else None


def log_exam_audit(
    db: Session,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    actor_id: Optional[uuid.UUID] = None,
    exam_id: Optional[uuid.UUID] = None,
    previous_value: Optional[str] = None,
    new_value: Optional[str] = None,
    reason: Optional[str] = None,
) -> ExamAuditLog:
    """Record an audit trail entry for exam series, occurrences, configurations, assignments, or results."""
    audit = ExamAuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_id=actor_id,
        exam_id=exam_id,
        previous_value=previous_value,
        new_value=new_value,
        reason=reason.strip() if reason and reason.strip() else None,
    )
    db.add(audit)
    db.flush()
    return audit


def list_exam_audit_logs(
    db: Session,
    exam_id: Optional[uuid.UUID] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[uuid.UUID] = None,
    limit: int = 200,
) -> List[ExamAuditLog]:
    """Retrieve audit history filtered by entity or exam series."""
    query = (
        db.query(ExamAuditLog)
        .options(joinedload(ExamAuditLog.actor), joinedload(ExamAuditLog.exam))
    )
    if exam_id:
        query = query.filter(ExamAuditLog.exam_id == exam_id)
    if entity_type:
        query = query.filter(ExamAuditLog.entity_type == entity_type)
    if entity_id:
        query = query.filter(ExamAuditLog.entity_id == entity_id)
    return query.order_by(desc(ExamAuditLog.created_at)).limit(limit).all()


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
    submission_days_after_exam: Optional[int] = None,
    is_active: bool = True,
    actor_id: Optional[uuid.UUID] = None,
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
        submission_days_after_exam=submission_days_after_exam,
        is_active=is_active,
        is_archived=False,
    )
    db.add(exam)
    db.flush()
    log_exam_audit(
        db,
        entity_type="SERIES",
        entity_id=exam.id,
        action="CREATED",
        actor_id=actor_id,
        exam_id=exam.id,
        new_value=json.dumps({"title": exam.title, "interval": recurrence_interval_weeks}, ensure_ascii=False),
    )
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
    submission_days_after_exam: Optional[int] = None,
    actor_id: Optional[uuid.UUID] = None,
) -> Exam:
    if not _lock_exam_row(db, exam_id):
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    if exam.is_archived:
        raise ExamValidationError("Cannot modify configuration of an archived exam series.")

    clean_title = (title or "").strip()
    if not clean_title:
        raise ExamValidationError("Exam title cannot be empty.")

    if recurrence_interval_weeks is not None and recurrence_interval_weeks < 1:
        raise ExamValidationError("Recurrence interval must be at least 1 week.")
    if first_exam_date and last_exam_date and first_exam_date > last_exam_date:
        raise ExamValidationError("First exam date cannot be after last exam date.")

    prev = {"title": exam.title, "description": exam.description, "interval": exam.recurrence_interval_weeks}

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
    if submission_days_after_exam is not None:
        exam.submission_days_after_exam = submission_days_after_exam

    log_exam_audit(
        db,
        entity_type="SERIES",
        entity_id=exam.id,
        action="UPDATED",
        actor_id=actor_id,
        exam_id=exam.id,
        previous_value=json.dumps(prev, ensure_ascii=False),
        new_value=json.dumps({"title": exam.title, "interval": exam.recurrence_interval_weeks}, ensure_ascii=False),
    )
    db.commit()
    db.refresh(exam)
    return exam


def archive_exam(db: Session, exam_id: uuid.UUID, actor_id: Optional[uuid.UUID] = None, reason: Optional[str] = None) -> Exam:
    if not _lock_exam_row(db, exam_id):
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    exam = get_exam_by_id(db, exam_id, populate_existing=True)
    if not exam:
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    exam.is_active = False
    exam.is_archived = True
    log_exam_audit(db, "SERIES", exam.id, "ARCHIVED", actor_id=actor_id, exam_id=exam.id, reason=reason)
    db.commit()
    db.refresh(exam)
    return exam


def restore_archived_exam_series(db: Session, exam_id: uuid.UUID, actor_id: Optional[uuid.UUID] = None, reason: Optional[str] = None) -> Exam:
    if not _lock_exam_row(db, exam_id):
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    exam = get_exam_by_id(db, exam_id, populate_existing=True)
    if not exam:
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    exam.is_active = True
    exam.is_archived = False
    log_exam_audit(db, "SERIES", exam.id, "RESTORED", actor_id=actor_id, exam_id=exam.id, reason=reason)
    db.commit()
    db.refresh(exam)
    return exam


def safe_delete_exam_series(db: Session, exam_id: uuid.UUID, actor_id: Optional[uuid.UUID] = None, force: bool = False) -> None:
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")

    has_results = any(len(s.results) > 0 for s in exam.sessions)
    if has_results and not force:
        raise ExamValidationError(
            "This exam series has submitted student results. Hard deletion is prevented to preserve historical results. "
            "Please archive the series instead."
        )

    log_exam_audit(
        db,
        entity_type="SERIES",
        entity_id=exam.id,
        action="DELETED",
        actor_id=actor_id,
        exam_id=exam.id,
        previous_value=json.dumps({"title": exam.title}, ensure_ascii=False),
    )
    db.delete(exam)
    db.commit()


def get_exam_by_id(db: Session, exam_id: uuid.UUID, populate_existing: bool = False) -> Optional[Exam]:
    query = db.query(Exam)
    if populate_existing:
        query = query.populate_existing()
    return (
        query
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



def get_exam_session_by_id(db: Session, session_id: uuid.UUID, populate_existing: bool = False) -> Optional[ExamSession]:
    query = db.query(ExamSession)
    if populate_existing:
        query = query.populate_existing()
    return (
        query
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
    reporting_groups_data: Optional[List[Dict[str, Any]]] = None,
    groups: Optional[List[Dict[str, Any]]] = None,
) -> ExamGradeTrackConfig:
    """Configure reporting groups and subject combinations for an eligible grade/track."""
    reporting_groups_data = reporting_groups_data if reporting_groups_data is not None else (groups or [])
    if not _lock_exam_row(db, exam_id):
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    if exam.is_archived:
        raise ExamValidationError("Cannot modify grade/track configuration of an archived exam series.")

    clean_grade = (grade or "").strip()
    if not clean_grade:
        raise ExamValidationError("Grade cannot be empty.")

    track = get_track_by_id(db, track_id)
    if not track:
        raise ExamValidationError(f"Academic track with id {track_id} not found.")

    if not reporting_groups_data:
        raise ExamValidationError("At least one reporting group must be configured.")

    track_subject_ids = {s.id for s in track.subjects}

    filtered_groups_data = []
    for grp in reporting_groups_data:
        grp_title = (grp.get("title") or "").strip()
        if not grp_title:
            raise ExamValidationError("Reporting group title cannot be empty.")
        raw_s_ids = list(dict.fromkeys(grp.get("subject_ids") or grp.get("subjects") or []))
        valid_s_ids = []
        for sid in raw_s_ids:
            if isinstance(sid, str):
                sid = uuid.UUID(sid)
            if sid in track_subject_ids:
                valid_s_ids.append(sid)
        if valid_s_ids:
            filtered_groups_data.append({
                "title": grp_title,
                "order_index": grp.get("order_index", len(filtered_groups_data)),
                "subject_ids": valid_s_ids,
            })

    if not filtered_groups_data:
        raise ExamValidationError(f"At least one valid subject for track '{track.name}' must be selected.")

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

    for idx, grp in enumerate(filtered_groups_data):
        grp_title = (grp.get("title") or "").strip()
        order_idx = int(grp.get("order_index", idx))
        s_ids = grp.get("subject_ids") or []
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


def delete_exam_grade_track_config(
    db: Session,
    config_id: uuid.UUID,
    exam_id: Optional[uuid.UUID] = None,
) -> None:
    config = db.query(ExamGradeTrackConfig).filter(ExamGradeTrackConfig.id == config_id).first()
    if not config:
        return
    if exam_id is not None and config.exam_id != exam_id:
        raise ExamNotFoundError("Grade/track configuration does not belong to this exam series.")
    _lock_exam_row(db, config.exam_id)
    exam = get_exam_by_id(db, config.exam_id)
    if exam and exam.is_archived:
        raise ExamValidationError("Cannot modify grade/track configuration of an archived exam series.")
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
    submission_deadline: Optional[datetime] = None,
    allow_late_submission: bool = True,
    commit: bool = True,
) -> ExamSession:
    if not _lock_exam_row(db, exam_id, share=True):
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    exam = get_exam_by_id(db, exam_id, populate_existing=True)
    if not exam:
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    if not exam.is_active or getattr(exam, 'is_archived', False):
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

    if submission_deadline is None and exam.submission_days_after_exam:
        dl_date = exam_date + timedelta(days=exam.submission_days_after_exam)
        submission_deadline = datetime(dl_date.year, dl_date.month, dl_date.day, 23, 59, 59)

    session = ExamSession(
        exam_id=exam.id,
        date=exam_date,
        title=title.strip() if title and title.strip() else None,
        status=status,
        is_manually_added=is_manually_added,
        sequence_order=sequence_order,
        submission_deadline=submission_deadline,
        allow_late_submission=allow_late_submission,
    )
    db.add(session)
    db.flush()

    series_track_ids = {gtc.track_id for gtc in exam.grade_track_configs} if exam.grade_track_configs else None

    for track_id, subject_ids in track_subjects_map.items():
        track = get_track_by_id(db, track_id)
        if not track:
            raise ExamValidationError(f"Academic track with id {track_id} not found.")
        if series_track_ids is not None and track_id not in series_track_ids:
            raise ExamValidationError(f"Academic track '{track.name}' is not configured for exam series '{exam.title}'.")
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

    if commit:
        db.commit()
        db.refresh(session)
        return get_exam_session_by_id(db, session.id)
    db.flush()
    return session


def update_exam_session(
    db: Session,
    session_id: uuid.UUID,
    exam_date: date,
    title: Optional[str] = None,
    track_subjects_map: Optional[Dict[uuid.UUID, List[uuid.UUID]]] = None,
) -> ExamSession:
    if not _lock_session_row(db, session_id):
        raise ExamSessionNotFoundError(f"Exam session with id {session_id} not found.")
    session = get_exam_session_by_id(db, session_id)
    if not session:
        raise ExamSessionNotFoundError(f"Exam session with id {session_id} not found.")
    if session.exam and (session.exam.is_archived or not session.exam.is_active):
        raise ExamValidationError("Cannot modify occurrences of an archived or inactive exam series.")

    session.date = exam_date
    session.title = title.strip() if title and title.strip() else None

    if track_subjects_map is not None:
        if len(track_subjects_map) == 0:
            raise ExamValidationError("At least one academic track must be configured for the exam.")

        validated_tracks = []
        for track_id, subject_ids in track_subjects_map.items():
            track = get_track_by_id(db, track_id)
            if not track:
                raise ExamValidationError(f"Academic track with id {track_id} not found.")
            if not subject_ids:
                raise ExamValidationError(f"At least one subject must be selected for track '{track.name}'.")

            track_valid_subject_ids = {s.id for s in track.subjects}
            for sub_id in subject_ids:
                if sub_id not in track_valid_subject_ids:
                    sub = get_subject_by_id(db, sub_id)
                    sub_name = sub.name if sub else str(sub_id)
                    raise ExamValidationError(
                        f"Subject '{sub_name}' is not valid for academic track '{track.name}'."
                    )
            validated_tracks.append((track.id, list(subject_ids)))

        # Remove existing configurations only after all replacements are validated
        for tc in list(session.track_configs):
            db.delete(tc)
        db.flush()

        for track_id, subject_ids in validated_tracks:
            track_config = ExamTrackConfiguration(
                exam_session_id=session.id,
                track_id=track_id,
            )
            db.add(track_config)
            db.flush()

            for sub_id in subject_ids:
                subj_config = ExamSubjectConfiguration(
                    exam_track_config_id=track_config.id,
                    subject_id=sub_id,
                )
                db.add(subj_config)

    for sa in session.exam.series_assignments:
        existing_ass = db.query(ExternalExamAssignment).filter(
            ExternalExamAssignment.exam_session_id == session.id,
            ExternalExamAssignment.student_id == sa.student_id,
        ).first()
        if not existing_ass:
            db.add(ExternalExamAssignment(exam_session_id=session.id, student_id=sa.student_id))

    db.commit()
    db.refresh(session)
    return get_exam_session_by_id(db, session.id)


def delete_exam_session(
    db: Session,
    session_id: uuid.UUID,
    actor_id: Optional[uuid.UUID] = None,
    force: bool = False,
) -> None:
    session = get_exam_session_by_id(db, session_id)
    if not session:
        raise ExamSessionNotFoundError(f"Exam session with id {session_id} not found.")

    if session.results and len(session.results) > 0 and not force:
        raise ExamValidationError(
            "This occurrence already has submitted student results. "
            "Ordinary deletion is prevented to protect student data. Please cancel the occurrence instead."
        )

    log_exam_audit(
        db,
        entity_type="OCCURRENCE",
        entity_id=session.id,
        action="DELETED",
        actor_id=actor_id,
        exam_id=session.exam_id,
        previous_value=json.dumps({"date": session.date.isoformat(), "title": session.title}, ensure_ascii=False),
    )
    db.delete(session)
    db.commit()


def cancel_exam_session(
    db: Session,
    session_id: uuid.UUID,
    actor_id: Optional[uuid.UUID] = None,
    reason: Optional[str] = None,
) -> ExamSession:
    if not _lock_session_row(db, session_id):
        raise ExamSessionNotFoundError(f"Exam session with id {session_id} not found.")
    session = get_exam_session_by_id(db, session_id)
    if not session:
        raise ExamSessionNotFoundError(f"Exam session with id {session_id} not found.")
    if session.exam and session.exam.is_archived:
        raise ExamValidationError("Cannot modify occurrences of an archived exam series.")

    session.status = "CANCELLED"
    session.skip_reason = reason.strip() if reason and reason.strip() else None

    log_exam_audit(
        db,
        entity_type="OCCURRENCE",
        entity_id=session.id,
        action="CANCELLED",
        actor_id=actor_id,
        exam_id=session.exam_id,
        reason=reason,
    )
    db.commit()
    db.refresh(session)
    return session


def generate_series_sessions(
    db: Session,
    exam_id: uuid.UUID,
    dates: Optional[List[date]] = None,
    actor_id: Optional[uuid.UUID] = None,
) -> List[ExamSession]:
    """Generate all scheduled occurrences for an exam series, preventing duplicates."""
    if not _lock_exam_row(db, exam_id):
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    if exam.is_archived or not exam.is_active:
        raise ExamValidationError(f"Cannot generate sessions for archived or inactive exam '{exam.title}'.")

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
        existing_dates.add(d)
        session = create_exam_session(
            db,
            exam_id=exam.id,
            exam_date=d,
            sequence_order=idx + 1,
            status="SCHEDULED",
            is_manually_added=False,
            commit=False,
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
    for s in created_sessions:
        db.refresh(s)
    return created_sessions


def skip_exam_session(
    db: Session,
    session_id: uuid.UUID,
    actor_id: Optional[uuid.UUID] = None,
    reason: Optional[str] = None,
    force_if_results: bool = False,
) -> ExamSession:
    """Mark an occurrence as No Exam (skipped) without shifting later dates."""
    if not _lock_session_row(db, session_id):
        raise ExamSessionNotFoundError(f"Exam session with id {session_id} not found.")
    session = get_exam_session_by_id(db, session_id)
    if not session:
        raise ExamSessionNotFoundError(f"Exam session with id {session_id} not found.")
    if session.exam and session.exam.is_archived:
        raise ExamValidationError("Cannot skip occurrences of an archived exam series.")
    if session.status == "CANCELLED":
        raise ExamValidationError("Cancelled occurrences are terminal and cannot be marked as skipped.")

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
    if not _lock_session_row(db, session_id):
        raise ExamSessionNotFoundError(f"Exam session with id {session_id} not found.")
    session = get_exam_session_by_id(db, session_id)
    if not session:
        raise ExamSessionNotFoundError(f"Exam session with id {session_id} not found.")
    if session.exam and session.exam.is_archived:
        raise ExamValidationError("Cannot restore occurrences of an archived exam series.")
    if session.status != "SKIPPED":
        raise ExamValidationError("Only skipped occurrences can be restored; cancelled occurrences cannot be reopened.")

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
    if not _lock_exam_row(db, exam_id):
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    if exam.is_archived or not exam.is_active:
        raise ExamValidationError("Cannot modify schedule of an archived or inactive exam series.")

    exam.recurrence_interval_weeks = new_interval_weeks
    exam.first_exam_date = new_first_date
    exam.last_exam_date = new_last_date
    exam.recurrence_weekday = new_weekday

    today = today_local()
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
        preserved_dates.add(d)
        session = create_exam_session(
            db,
            exam_id=exam.id,
            exam_date=d,
            sequence_order=idx + 1,
            status="SCHEDULED",
            is_manually_added=False,
            commit=False,
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
    for s in created:
        db.refresh(s)
    return created


def bulk_skip_exam_sessions(
    db: Session,
    session_ids: List[uuid.UUID],
    actor_id: Optional[uuid.UUID] = None,
    reason: Optional[str] = None,
    force_if_results: bool = False,
) -> Dict[str, Any]:
    skipped = []
    skipped_count = 0
    with_results = 0
    for sid in sorted(set(session_ids)):
        if not _lock_session_row(db, sid):
            continue
        sess = get_exam_session_by_id(db, sid)
        if not sess:
            continue
        if sess.exam and sess.exam.is_archived:
            continue
        if sess.status == "CANCELLED":
            continue
        if sess.results and len(sess.results) > 0:
            with_results += 1
            if not force_if_results:
                continue
        sess.status = "SKIPPED"
        sess.skip_reason = reason.strip() if reason and reason.strip() else None
        log_exam_audit(db, "OCCURRENCE", sess.id, "SKIPPED", actor_id=actor_id, exam_id=sess.exam_id, reason=reason)
        skipped.append(sess)
        skipped_count += 1
    db.commit()
    return {"affected_count": skipped_count, "skipped_with_results_count": with_results, "sessions": skipped}


def bulk_cancel_exam_sessions(
    db: Session,
    session_ids: List[uuid.UUID],
    actor_id: Optional[uuid.UUID] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    cancelled = []
    for sid in sorted(set(session_ids)):
        if not _lock_session_row(db, sid):
            continue
        sess = get_exam_session_by_id(db, sid)
        if not sess:
            continue
        if sess.exam and sess.exam.is_archived:
            continue
        sess.status = "CANCELLED"
        sess.skip_reason = reason.strip() if reason and reason.strip() else None
        log_exam_audit(db, "OCCURRENCE", sess.id, "CANCELLED", actor_id=actor_id, exam_id=sess.exam_id, reason=reason)
        cancelled.append(sess)
    db.commit()
    return {"affected_count": len(cancelled), "sessions": cancelled}


def bulk_restore_exam_sessions(
    db: Session,
    session_ids: List[uuid.UUID],
    actor_id: Optional[uuid.UUID] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    restored = []
    for sid in sorted(set(session_ids)):
        if not _lock_session_row(db, sid):
            continue
        sess = get_exam_session_by_id(db, sid)
        if not sess:
            continue
        if sess.exam and sess.exam.is_archived:
            continue
        if sess.status != "SKIPPED":
            continue
        sess.status = "SCHEDULED"
        sess.skip_reason = None
        log_exam_audit(db, "OCCURRENCE", sess.id, "RESTORED", actor_id=actor_id, exam_id=sess.exam_id, reason=reason)
        restored.append(sess)
    db.commit()
    return {"affected_count": len(restored), "sessions": restored}


def extend_exam_recurrence(
    db: Session,
    exam_id: uuid.UUID,
    new_last_exam_date: date,
    actor_id: Optional[uuid.UUID] = None,
) -> List[ExamSession]:
    """Extend a recurring exam series to a later date without modifying earlier occurrences."""
    if not _lock_exam_row(db, exam_id):
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    if exam.is_archived or not exam.is_active:
        raise ExamValidationError("Cannot extend schedule of an archived or inactive exam series.")
    if not exam.first_exam_date or not exam.recurrence_interval_weeks:
        raise ExamValidationError("Exam series does not have recurrence configured.")
    if exam.last_exam_date and new_last_exam_date <= exam.last_exam_date:
        raise ExamValidationError("New end date must be after the current last exam date.")

    old_end = exam.last_exam_date
    exam.last_exam_date = new_last_exam_date

    all_dates = calculate_recurring_dates(
        first_exam_date=exam.first_exam_date,
        last_exam_date=new_last_exam_date,
        interval_weeks=exam.recurrence_interval_weeks,
        weekday=exam.recurrence_weekday,
    )
    existing_dates = {s.date for s in exam.sessions}
    new_dates = [d for d in all_dates if d not in existing_dates]

    created = []
    start_order = len(exam.sessions) + 1
    for idx, d in enumerate(new_dates):
        session = create_exam_session(
            db,
            exam_id=exam.id,
            exam_date=d,
            sequence_order=start_order + idx,
            status="SCHEDULED",
            commit=False,
        )
        log_exam_audit(db, "OCCURRENCE", session.id, "CREATED", actor_id=actor_id, exam_id=exam.id, reason="Schedule extended")
        created.append(session)

    log_exam_audit(
        db,
        "SERIES",
        exam.id,
        "EXTENDED",
        actor_id=actor_id,
        exam_id=exam.id,
        previous_value=str(old_end),
        new_value=str(new_last_exam_date),
    )
    db.commit()
    for s in created:
        db.refresh(s)
    return created


def bulk_add_manual_sessions(
    db: Session,
    exam_id: uuid.UUID,
    dates_and_titles: List[Dict[str, Any]],
    actor_id: Optional[uuid.UUID] = None,
) -> List[ExamSession]:
    """Add multiple manually specified dates to a series."""
    if not _lock_exam_row(db, exam_id):
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    if exam.is_archived or not exam.is_active:
        raise ExamValidationError("Cannot add occurrences to an archived or inactive exam series.")

    created = []
    for item in dates_and_titles:
        d = item.get("date")
        if isinstance(d, str):
            d = date.fromisoformat(d)
        t = item.get("title")
        sess = create_exam_session(
            db,
            exam_id=exam.id,
            exam_date=d,
            title=t,
            status="SCHEDULED",
            is_manually_added=True,
            commit=False,
        )
        log_exam_audit(db, "OCCURRENCE", sess.id, "MANUAL_ADDED", actor_id=actor_id, exam_id=exam.id, reason="Bulk manual add")
        created.append(sess)
    db.commit()
    for s in created:
        db.refresh(s)
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

    today = today_local(getattr(student, "timezone", None))
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

        # Skipped, cancelled, archived, or inactive occurrences must NOT appear as open exams
        if s.status in ("SKIPPED", "CANCELLED") and not student_result:
            continue
        if (s.exam.is_archived or not s.exam.is_active) and not student_result:
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
    populate_existing: bool = False,
) -> Optional[StudentExamResult]:
    query = db.query(StudentExamResult)
    if populate_existing:
        query = query.populate_existing()
    return (
        query
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
    student_or_session_id: Any = None,
    session_id_or_student: Any = None,
    exam_session_id: Optional[uuid.UUID] = None,
    student: Optional[User] = None,
    student_id: Optional[uuid.UUID] = None,
    subject_data: Optional[List[Dict[str, Any]]] = None,
    group_data: Optional[List[Dict[str, Any]]] = None,
    group_percentages: Optional[Dict[Any, float]] = None,
    overall_rank: Optional[int] = None,
    notes: Optional[str] = None,
    report_card_file_path: Optional[str] = None,
    report_card_file_name: Optional[str] = None,
    is_tutor_override: bool = False,
) -> StudentExamResult:
    if isinstance(student_or_session_id, User):
        student = student_or_session_id
    elif isinstance(student_or_session_id, uuid.UUID):
        exam_session_id = student_or_session_id

    if isinstance(session_id_or_student, uuid.UUID):
        exam_session_id = session_id_or_student
    elif isinstance(session_id_or_student, User):
        student = session_id_or_student

    if student is None and student_id is not None:
        student = db.query(User).get(student_id)

    if not student:
        raise ExamValidationError("Student not found.")
    if not student.academic_track_id:
        raise ExamValidationError("Student has no academic track assigned.")

    if not _lock_session_row(db, exam_session_id, share=True):
        raise ExamSessionNotFoundError(f"Exam session with id {exam_session_id} not found.")
    session = get_exam_session_by_id(db, exam_session_id, populate_existing=True)
    if not session:
        raise ExamSessionNotFoundError(f"Exam session with id {exam_session_id} not found.")

    if session.status in ("SKIPPED", "CANCELLED"):
        raise ExamValidationError("Cannot submit results for a skipped or cancelled exam occurrence.")
    if session.exam and (session.exam.is_archived or not session.exam.is_active) and not is_tutor_override:
        raise ExamValidationError("Cannot submit results for an archived or inactive exam series.")

    now = now_utc()
    is_late = False
    s_deadline = session.submission_deadline
    if s_deadline and s_deadline.tzinfo is None:
        from datetime import timezone
        s_deadline = s_deadline.replace(tzinfo=timezone.utc)
    if s_deadline and now > s_deadline:
        is_late = True
        if not getattr(session, 'allow_late_submission', True) and not is_tutor_override:
            raise ExamValidationError("Submission deadline has passed for this exam occurrence.")

    existing_result = get_student_exam_result(db, student.id, session.id)
    if existing_result:
        raise DuplicateExamResultError("Results have already been submitted for this exam occurrence.")

    track_config = next(
        (tc for tc in session.track_configs if tc.track_id == student.academic_track_id),
        None,
    )
    grade_track_cfg = get_student_series_grade_track_config(db, session.exam_id, student)
    if not track_config and not grade_track_cfg:
        raise ExamValidationError("This exam is not available for your academic track or grade.")

    if group_percentages:
        group_data = group_data or []
        for gid, pct in group_percentages.items():
            group_data.append({"reporting_group_id": gid, "percentage": pct})

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
        valid_rg_ids = {rg.id for rg in grade_track_cfg.reporting_groups} if grade_track_cfg else set()
        for grp in group_data:
            rg_id = grp.get("reporting_group_id") or grp.get("group_id")
            if isinstance(rg_id, str):
                rg_id = uuid.UUID(rg_id)
            if rg_id is not None and rg_id not in valid_rg_ids:
                raise ExamValidationError("Invalid reporting group for your grade and academic track.")
            g_title = (grp.get("group_title") or grp.get("title") or "").strip()
            if not g_title and rg_id:
                rg_obj = db.query(ExamReportingGroup).get(rg_id)
                if rg_obj:
                    g_title = rg_obj.title
            if not g_title:
                raise ExamValidationError("Reporting group title cannot be empty.")
            pct = _validate_percentage(grp.get("percentage", 0.0))

            parsed_group_items.append((rg_id, g_title, pct, grp.get("included_subject_names")))

    parsed_subject_items = []
    if subject_data:
        configured_subject_ids = {sc.subject_id for sc in track_config.subject_configs} if track_config else set()
        effective_subjects = get_student_effective_subjects(student)
        effective_subject_ids = {s.id for s in effective_subjects}
        allowed_subject_ids = configured_subject_ids.intersection(effective_subject_ids) if track_config else effective_subject_ids

        seen_subjects: Set[uuid.UUID] = set()
        for item in subject_data:
            sub_id = item.get("subject_id")
            if isinstance(sub_id, str):
                sub_id = uuid.UUID(sub_id)
            if not sub_id or (not is_tutor_override and sub_id not in allowed_subject_ids):
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

            percentage = _validate_percentage(item.get("percentage", 0.0))

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
        is_late=is_late,
        is_reviewed=False,
        is_tutor_corrected=False,
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

    log_exam_audit(db, "RESULT", result.id, "SUBMITTED", actor_id=student.id, exam_id=session.exam_id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateExamResultError("Results have already been submitted for this exam occurrence.")
    return get_student_exam_result_by_id(db, result.id)


def mark_exam_result_reviewed(
    db: Session,
    result_id: uuid.UUID,
    actor_id: Optional[uuid.UUID] = None,
    tutor_id: Optional[uuid.UUID] = None,
    notes: Optional[str] = None,
) -> StudentExamResult:
    effective_actor = actor_id or tutor_id
    if not _lock_result_row(db, result_id):
        raise ExamResultNotFoundError(f"Result {result_id} not found.")
    result = get_student_exam_result_by_id(db, result_id, populate_existing=True)
    if not result:
        raise ExamResultNotFoundError(f"Result {result_id} not found.")

    result.is_reviewed = True
    result.reviewed_by_id = effective_actor
    result.reviewed_at = now_utc()
    if notes and notes.strip():
        result.notes = (result.notes + "\n" if result.notes else "") + f"[Review Note]: {notes.strip()}"

    log_exam_audit(
        db,
        entity_type="RESULT",
        entity_id=result.id,
        action="REVIEWED",
        actor_id=effective_actor,
        exam_id=result.exam_session.exam_id,
        reason=notes,
    )
    db.commit()
    db.refresh(result)
    return result


def reopen_exam_result(
    db: Session,
    result_id: uuid.UUID,
    actor_id: Optional[uuid.UUID] = None,
    tutor_id: Optional[uuid.UUID] = None,
    reason: Optional[str] = None,
) -> StudentExamResult:
    effective_actor = actor_id or tutor_id
    if not _lock_result_row(db, result_id):
        raise ExamResultNotFoundError(f"Result {result_id} not found.")
    result = get_student_exam_result_by_id(db, result_id, populate_existing=True)
    if not result:
        raise ExamResultNotFoundError(f"Result {result_id} not found.")

    result.is_reviewed = False
    result.is_tutor_corrected = False
    result.reviewed_at = None

    log_exam_audit(
        db,
        entity_type="RESULT",
        entity_id=result.id,
        action="REOPENED",
        actor_id=effective_actor,
        exam_id=result.exam_session.exam_id,
        reason=reason,
    )
    db.commit()
    db.refresh(result)
    return result


def tutor_correct_exam_result(
    db: Session,
    result_id: uuid.UUID,
    actor_id: Optional[uuid.UUID] = None,
    tutor_id: Optional[uuid.UUID] = None,
    group_data: Optional[List[Dict[str, Any]]] = None,
    group_percentages: Optional[Dict[Any, float]] = None,
    subject_data: Optional[List[Dict[str, Any]]] = None,
    overall_rank: Optional[int] = None,
    notes: Optional[str] = None,
    reason: Optional[str] = None,
) -> StudentExamResult:
    effective_actor = actor_id or tutor_id
    if not _lock_result_row(db, result_id):
        raise ExamResultNotFoundError(f"Result {result_id} not found.")
    result = get_student_exam_result_by_id(db, result_id, populate_existing=True)
    if not result:
        raise ExamResultNotFoundError(f"Result {result_id} not found.")

    prev_state = {
        "overall_rank": result.overall_rank,
        "notes": result.notes,
        "groups": [{"title": gr.group_title, "pct": gr.percentage} for gr in result.group_results],
    }

    result.is_tutor_corrected = True
    if overall_rank is not None:
        try:
            clean_rank = int(overall_rank)
            if clean_rank <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise ExamValidationError("Overall rank must be a positive integer if provided.")
        result.overall_rank = clean_rank
    if notes is not None:
        result.notes = notes

    if group_percentages is not None:
        group_data = []
        for gid, pct in group_percentages.items():
            group_data.append({"reporting_group_id": gid, "percentage": pct})

    parsed_groups_corr = None
    if group_data is not None:
        parsed_groups_corr = []
        for grp in group_data:
            rg_id = grp.get("reporting_group_id") or grp.get("group_id")
            if isinstance(rg_id, str):
                rg_id = uuid.UUID(rg_id)
            g_title = (grp.get("group_title") or grp.get("title") or "").strip()
            if not g_title and rg_id:
                rg_obj = db.query(ExamReportingGroup).get(rg_id)
                if rg_obj:
                    g_title = rg_obj.title
            if not g_title:
                raise ExamValidationError("Reporting group title cannot be empty.")
            pct = _validate_percentage(grp.get("percentage", 0.0))
            parsed_groups_corr.append((rg_id, g_title, pct, grp.get("included_subject_names")))

    parsed_subjects_corr = None
    if subject_data is not None:
        parsed_subjects_corr = []
        for item in subject_data:
            sub_id = item.get("subject_id")
            if isinstance(sub_id, str):
                sub_id = uuid.UUID(sub_id)
            try:
                correct = int(item.get("correct_answers", 0))
                incorrect = int(item.get("incorrect_answers", 0))
            except (ValueError, TypeError):
                raise ExamValidationError("Correct and incorrect answers must be valid integers.")
            if correct < 0 or incorrect < 0:
                raise ExamValidationError("Correct and incorrect counts must be non-negative integers.")
            pct = _validate_percentage(item.get("percentage", 0.0))
            parsed_subjects_corr.append((sub_id, correct, incorrect, pct))

    if parsed_groups_corr is not None:
        for gr in list(result.group_results):
            db.delete(gr)
        db.flush()
        for rg_id, g_title, pct, inc_names in parsed_groups_corr:
            group_res = StudentExamGroupResult(
                student_exam_result_id=result.id,
                reporting_group_id=rg_id,
                group_title=g_title,
                percentage=pct,
                included_subject_names=inc_names,
            )
            db.add(group_res)

    if parsed_subjects_corr is not None:
        for sr in list(result.subject_results):
            db.delete(sr)
        db.flush()
        for sub_id, correct, incorrect, pct in parsed_subjects_corr:
            db.add(StudentExamSubjectResult(
                student_exam_result_id=result.id,
                subject_id=sub_id,
                correct_answers=correct,
                incorrect_answers=incorrect,
                percentage=pct,
            ))

    new_state = {
        "overall_rank": result.overall_rank,
        "notes": result.notes,
        "groups": [{"title": gr.group_title, "pct": gr.percentage} for gr in result.group_results],
    }
    log_exam_audit(
        db,
        entity_type="RESULT",
        entity_id=result.id,
        action="CORRECTED",
        actor_id=effective_actor,
        exam_id=result.exam_session.exam_id,
        previous_value=json.dumps(prev_state, ensure_ascii=False),
        new_value=json.dumps(new_state, ensure_ascii=False),
        reason=reason,
    )
    db.commit()
    db.refresh(result)
    return result


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
    is_tutor_override: bool = False,
) -> StudentExamResult:
    # Acquire shared lock on parent exam/session before exclusive lock on result row (Exam -> ExamSession -> StudentExamResult)
    sess_row = db.query(StudentExamResult.exam_session_id).filter(StudentExamResult.id == result_id).first()
    if sess_row:
        _lock_session_row(db, sess_row[0], share=True)

    if not _lock_result_row(db, result_id):
        raise ExamResultNotFoundError(f"Exam result with id {result_id} not found.")
    result = get_student_exam_result_by_id(db, result_id, populate_existing=True)
    if not result:
        raise ExamResultNotFoundError(f"Exam result with id {result_id} not found.")

    if result.student_id != student.id and not is_tutor_override:
        raise ExamValidationError("You are not authorized to edit this result.")

    if result.is_reviewed or getattr(result, "is_tutor_corrected", False):
        raise ExamValidationError("Cannot edit an exam result that has been reviewed or corrected by a tutor without reopening.")

    session = result.exam_session
    if session:
        if session.status in ("SKIPPED", "CANCELLED") and not is_tutor_override:
            raise ExamValidationError("Cannot edit results for a skipped or cancelled exam occurrence.")
        if session.exam and (session.exam.is_archived or not session.exam.is_active) and not is_tutor_override:
            raise ExamValidationError("Cannot edit results for an archived or inactive exam series.")

        now = now_utc()
        s_deadline = session.submission_deadline
        if s_deadline and s_deadline.tzinfo is None:
            s_deadline = s_deadline.replace(tzinfo=timezone.utc)
        if s_deadline and now > s_deadline:
            if not getattr(session, 'allow_late_submission', True) and not is_tutor_override:
                raise ExamValidationError("Submission deadline has passed for this exam occurrence.")
            result.is_late = True

    clean_rank = None
    if overall_rank is not None:
        try:
            clean_rank = int(overall_rank)
            if clean_rank <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise ExamValidationError("Overall rank must be a positive integer if provided.")

    prev_state = {
        "overall_rank": result.overall_rank,
        "notes": result.notes,
        "report_card_file_name": result.report_card_file_name,
        "is_late": result.is_late,
        "groups": [{"title": gr.group_title, "pct": gr.percentage} for gr in result.group_results],
        "subjects": [
            {
                "subject_id": str(sr.subject_id),
                "correct": sr.correct_answers,
                "incorrect": sr.incorrect_answers,
                "percentage": sr.percentage,
            }
            for sr in result.subject_results
        ],
    }

    result.overall_rank = clean_rank
    result.notes = notes.strip() if notes and notes.strip() else None
    if report_card_file_path:
        result.report_card_file_path = report_card_file_path
        result.report_card_file_name = report_card_file_name

    new_groups = []
    if group_data is not None:
        if len(group_data) == 0 and not subject_data:
            raise ExamValidationError("At least one subject or group result must be submitted.")
        grade_track_cfg = get_student_series_grade_track_config(db, session.exam_id, student) if session else None
        valid_rg_ids = {rg.id for rg in grade_track_cfg.reporting_groups} if grade_track_cfg else {gr.reporting_group_id for gr in result.group_results if gr.reporting_group_id}
        parsed_update_groups = []
        for grp in group_data:
            g_title = (grp.get("group_title") or grp.get("title") or "").strip()
            if not g_title:
                raise ExamValidationError("Reporting group title cannot be empty.")
            pct = _validate_percentage(grp.get("percentage", 0.0))
            rg_id = grp.get("reporting_group_id")
            if isinstance(rg_id, str):
                rg_id = uuid.UUID(rg_id)
            if rg_id is not None and valid_rg_ids and rg_id not in valid_rg_ids:
                raise ExamValidationError("Invalid reporting group for your grade and academic track.")
            parsed_update_groups.append((rg_id, g_title, pct, grp.get("included_subject_names")))

        for gr in list(result.group_results):
            db.delete(gr)
        db.flush()
        for rg_id, g_title, pct, inc_names in parsed_update_groups:
            group_res = StudentExamGroupResult(
                student_exam_result_id=result.id,
                reporting_group_id=rg_id,
                group_title=g_title,
                percentage=pct,
                included_subject_names=inc_names,
            )
            db.add(group_res)
            new_groups.append({"title": g_title, "pct": pct})
    else:
        new_groups = prev_state["groups"]

    new_subjects = []
    if subject_data is not None:
        if len(subject_data) == 0 and not group_data:
            raise ExamValidationError("At least one subject or group result must be submitted.")
        track_config = (
            next((tc for tc in session.track_configs if tc.track_id == student.academic_track_id), None)
            if session
            else None
        )
        configured_subject_ids = {sc.subject_id for sc in track_config.subject_configs} if track_config else set()
        effective_subject_ids = {s.id for s in get_student_effective_subjects(student)}
        allowed_subject_ids = configured_subject_ids.intersection(effective_subject_ids) if track_config else effective_subject_ids

        seen_subjects: Set[uuid.UUID] = set()
        parsed_update_subjects = []
        for item in subject_data:
            sub_id = item.get("subject_id")
            if isinstance(sub_id, str):
                sub_id = uuid.UUID(sub_id)
            if not sub_id or (not is_tutor_override and sub_id not in allowed_subject_ids):
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
            percentage = _validate_percentage(item.get("percentage", 0.0))
            parsed_update_subjects.append((sub_id, correct, incorrect, percentage))

        for sr in list(result.subject_results):
            db.delete(sr)
        db.flush()
        for sub_id, correct, incorrect, percentage in parsed_update_subjects:
            subject_result = StudentExamSubjectResult(
                student_exam_result_id=result.id,
                subject_id=sub_id,
                correct_answers=correct,
                incorrect_answers=incorrect,
                percentage=percentage,
            )
            db.add(subject_result)
            new_subjects.append({
                "subject_id": str(sub_id),
                "correct": correct,
                "incorrect": incorrect,
                "percentage": percentage,
            })
    else:
        new_subjects = prev_state["subjects"]

    new_state = {
        "overall_rank": result.overall_rank,
        "notes": result.notes,
        "report_card_file_name": result.report_card_file_name,
        "is_late": result.is_late,
        "groups": new_groups,
        "subjects": new_subjects,
    }

    log_exam_audit(
        db,
        entity_type="RESULT",
        entity_id=result.id,
        action="UPDATED",
        actor_id=student.id,
        exam_id=session.exam_id if session else None,
        previous_value=json.dumps(prev_state, ensure_ascii=False),
        new_value=json.dumps(new_state, ensure_ascii=False),
    )

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
            "is_reviewed": getattr(r, "is_reviewed", False),
            "is_late": getattr(r, "is_late", False),
            "is_tutor_corrected": getattr(r, "is_tutor_corrected", False),
            "reviewed_at": r.reviewed_at.strftime('%Y-%m-%d %H:%M') if getattr(r, "reviewed_at", None) else None,
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

    variants = {
        "10": ["10", "دهم"],
        "دهم": ["10", "دهم"],
        "11": ["11", "یازدهم"],
        "یازدهم": ["11", "یازدهم"],
        "12": ["12", "دوازدهم"],
        "دوازدهم": ["12", "دوازدهم"],
    }.get(str(student.grade).strip(), [str(student.grade).strip()])

    return (
        db.query(ExamGradeTrackConfig)
        .options(
            joinedload(ExamGradeTrackConfig.reporting_groups)
            .joinedload(ExamReportingGroup.subjects)
        )
        .filter(
            ExamGradeTrackConfig.exam_id == exam_id,
            ExamGradeTrackConfig.grade.in_(variants),
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
    if not _lock_session_row(db, exam_session_id, share=True):
        raise ExamSessionNotFoundError(f"Exam session with id {exam_session_id} not found.")
    session = get_exam_session_by_id(db, exam_session_id, populate_existing=True)
    if not session:
        raise ExamSessionNotFoundError(f"Exam session with id {exam_session_id} not found.")
    if session.exam and (session.exam.is_archived or not session.exam.is_active):
        raise ExamValidationError("Cannot assign students to an archived or inactive exam series.")
    if session.status in ("CANCELLED", "SKIPPED"):
        raise ExamValidationError("Cannot assign students to a skipped or cancelled exam occurrence.")

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
    sync_omitted: bool = True,
    actor_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Assign an exam series to eligible students and optionally revoke omitted assignments."""
    if not _lock_exam_row(db, exam_id):
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise ExamNotFoundError(f"Exam with id {exam_id} not found.")
    if exam.is_archived or not exam.is_active:
        raise ExamValidationError("Cannot assign students to an archived or inactive exam series.")

    unique_student_ids = list(dict.fromkeys(student_ids))
    eval_result = evaluate_students_eligibility(db, exam_id, unique_student_ids)
    if eval_result["ineligible"]:
        reasons = "; ".join(f"Student {item.get('student').full_name if item.get('student') else item['student_id']}: {item['reason']}" for item in eval_result["ineligible"])
        raise IneligibleStudentError(f"Cannot assign series to incompatible students: {reasons}")

    assigned_count = 0
    selected_ids = {item["student"].id for item in eval_result["eligible"]}
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

    revoked_count = 0
    if sync_omitted:
        existing_series_assignments = db.query(ExamSeriesAssignment).filter(
            ExamSeriesAssignment.exam_id == exam.id
        ).all()
        session_ids = [s.id for s in exam.sessions]
        for sa in existing_series_assignments:
            if sa.student_id not in selected_ids:
                db.delete(sa)
                revoked_count += 1
                if session_ids:
                    submitted_session_ids = {
                        sr.exam_session_id
                        for sr in db.query(StudentExamResult).filter(
                            StudentExamResult.student_id == sa.student_id,
                            StudentExamResult.exam_session_id.in_(session_ids),
                        ).all()
                    }
                    unsubmitted_eas = db.query(ExternalExamAssignment).filter(
                        ExternalExamAssignment.student_id == sa.student_id,
                        ExternalExamAssignment.exam_session_id.in_(session_ids),
                    ).all()
                    for ea in unsubmitted_eas:
                        if ea.exam_session_id not in submitted_session_ids:
                            db.delete(ea)
                log_exam_audit(
                    db,
                    "SERIES",
                    exam.id,
                    "UNASSIGNED",
                    actor_id=actor_id,
                    exam_id=exam.id,
                    reason=f"Revoked omitted assignment for student {sa.student_id}",
                )

    db.commit()
    return {
        "assigned_count": assigned_count,
        "revoked_count": revoked_count,
        "eligible_count": len(eval_result["eligible"]),
    }


def bulk_assign_occurrences_to_students(
    db: Session,
    session_ids: List[uuid.UUID],
    student_ids: List[uuid.UUID],
    actor_id: Optional[uuid.UUID] = None,
    allow_partial: bool = False,
) -> Dict[str, Any]:
    """Assign specific exam occurrences to multiple students, validating eligibility."""
    sessions = db.query(ExamSession).options(joinedload(ExamSession.exam)).filter(ExamSession.id.in_(session_ids)).all()
    if not sessions:
        raise ExamValidationError("No valid exam sessions found.")

    for sess in sessions:
        if sess.exam and (sess.exam.is_archived or not sess.exam.is_active):
            raise ExamValidationError("Cannot assign students to occurrences of an archived or inactive exam series.")
        if sess.status in ("CANCELLED", "SKIPPED"):
            raise ExamValidationError("Cannot assign students to a skipped or cancelled exam occurrence.")

    students = db.query(User).filter(User.id.in_(student_ids), User.role == "STUDENT", User.is_active == True).all()
    assigned_count = 0

    for sess in sessions:
        eval_result = evaluate_students_eligibility(db, sess.exam_id, [s.id for s in students])
        if not allow_partial and eval_result["ineligible"]:
            first_ineligible = eval_result["ineligible"][0]
            st = first_ineligible["student"]
            reason = first_ineligible["reason"]
            raise IneligibleStudentError(f"Student '{st.full_name or st.username}' is not eligible for this exam: {reason}")

        for item in eval_result["eligible"]:
            st = item["student"]
            existing = db.query(ExternalExamAssignment).filter(
                ExternalExamAssignment.exam_session_id == sess.id,
                ExternalExamAssignment.student_id == st.id,
            ).first()
            if not existing:
                db.add(ExternalExamAssignment(exam_session_id=sess.id, student_id=st.id))
                assigned_count += 1
                log_exam_audit(db, "ASSIGNMENT", sess.id, "ASSIGNED", actor_id=actor_id, exam_id=sess.exam_id, reason=f"Assigned to {st.username}")

    db.commit()
    return {"assigned_count": assigned_count, "sessions_count": len(sessions), "students_count": len(students)}


def bulk_remove_students_from_future_occurrences(
    db: Session,
    exam_id: uuid.UUID,
    student_ids: List[uuid.UUID],
    actor_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Remove selected students from future occurrences while strictly preserving past or completed submissions."""
    today = today_local()
    future_sessions = db.query(ExamSession).filter(ExamSession.exam_id == exam_id, ExamSession.date >= today).all()
    future_session_ids = [s.id for s in future_sessions]

    # Find submitted result session ids to preserve them
    submitted_pairs = {
        (r.exam_session_id, r.student_id)
        for r in db.query(StudentExamResult).filter(
            StudentExamResult.student_id.in_(student_ids),
            StudentExamResult.exam_session_id.in_(future_session_ids),
        ).all()
    }

    removed_count = 0
    assignments = db.query(ExternalExamAssignment).filter(
        ExternalExamAssignment.student_id.in_(student_ids),
        ExternalExamAssignment.exam_session_id.in_(future_session_ids),
    ).all()

    for a in assignments:
        if (a.exam_session_id, a.student_id) not in submitted_pairs:
            db.delete(a)
            removed_count += 1

    # Also remove series assignment if removing from all
    for sid in student_ids:
        sa = db.query(ExamSeriesAssignment).filter(
            ExamSeriesAssignment.exam_id == exam_id,
            ExamSeriesAssignment.student_id == sid,
        ).first()
        if sa:
            db.delete(sa)
            log_exam_audit(db, "SERIES", exam_id, "REMOVED", actor_id=actor_id, exam_id=exam_id, reason=f"Removed student {sid}")

    db.commit()
    return {"removed_assignments_count": removed_count, "affected_students_count": len(student_ids)}


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

    # Only remove future unsubmitted occurrences; preserve historical records
    today = today_local()
    future_sessions = (
        db.query(ExamSession)
        .filter(
            ExamSession.exam_id == exam_id,
            ExamSession.date >= today,
        )
        .all()
    )
    future_session_ids = [s.id for s in future_sessions]

    if future_session_ids:
        submitted_session_ids = {
            sr.exam_session_id
            for sr in db.query(StudentExamResult).filter(
                StudentExamResult.student_id == student_id,
                StudentExamResult.exam_session_id.in_(future_session_ids)
            ).all()
        }

        unsubmitted_assignments = db.query(ExternalExamAssignment).filter(
            ExternalExamAssignment.student_id == student_id,
            ExternalExamAssignment.exam_session_id.in_(future_session_ids),
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
        pct = _validate_percentage(item.get("percentage", 0.0), subject_label=s_name)

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


def get_bulk_series_submission_overview(
    db: Session,
    exam_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Provide a high-level matrix of assigned, submitted, awaiting, reviewed, and missing results."""
    query = db.query(ExamSession).options(
        joinedload(ExamSession.exam),
        joinedload(ExamSession.assignments).joinedload(ExternalExamAssignment.student),
        joinedload(ExamSession.results).joinedload(StudentExamResult.group_results),
    )
    if exam_id:
        query = query.filter(ExamSession.exam_id == exam_id)
    sessions = query.order_by(desc(ExamSession.date)).all()

    now = now_utc()
    today = today_local()

    total_assigned = 0
    total_submitted = 0
    total_reviewed = 0
    total_awaiting = 0
    total_missing = 0

    session_rows = []
    for s in sessions:
        res_map = {r.student_id: r for r in s.results}
        assigned_students = [a.student for a in s.assignments if a.student]
        total_assigned += len(assigned_students)

        s_submitted = 0
        s_reviewed = 0
        s_awaiting = 0
        s_missing = 0

        student_details = []
        for st in assigned_students:
            res = res_map.get(st.id)
            if res:
                s_submitted += 1
                if res.is_reviewed:
                    s_reviewed += 1
                student_details.append({
                    "student_id": str(st.id),
                    "name": st.full_name or st.username,
                    "grade": st.grade,
                    "status": "Reviewed" if res.is_reviewed else "Submitted",
                    "overall_rank": res.overall_rank,
                    "is_late": res.is_late,
                    "is_corrected": res.is_tutor_corrected,
                })
            else:
                # Not submitted
                is_overdue = bool(s.submission_deadline and now > s.submission_deadline)
                if s.date <= today:
                    if is_overdue:
                        s_missing += 1
                    else:
                        s_awaiting += 1
                status_label = "Missing" if is_overdue else ("Awaiting" if s.date <= today else "Upcoming")
                student_details.append({
                    "student_id": str(st.id),
                    "name": st.full_name or st.username,
                    "grade": st.grade,
                    "status": status_label,
                    "overall_rank": None,
                    "is_late": False,
                    "is_corrected": False,
                })

        total_submitted += s_submitted
        total_reviewed += s_reviewed
        total_awaiting += s_awaiting
        total_missing += s_missing

        session_rows.append({
            "session_id": str(s.id),
            "exam_title": s.exam.title if s.exam else "",
            "date": s.date.isoformat(),
            "status": s.status,
            "assigned_count": len(assigned_students),
            "submitted_count": s_submitted,
            "reviewed_count": s_reviewed,
            "awaiting_count": s_awaiting,
            "missing_count": s_missing,
            "deadline": s.submission_deadline.isoformat() if s.submission_deadline else None,
            "students": student_details,
        })

    return {
        "summary": {
            "total_assigned": total_assigned,
            "total_submitted": total_submitted,
            "total_reviewed": total_reviewed,
            "total_awaiting": total_awaiting,
            "total_missing": total_missing,
        },
        "sessions": session_rows,
    }


def compare_students_on_session(
    db: Session,
    session_id: uuid.UUID,
    grade: Optional[str] = None,
    track_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Compare students taking the same occurrence strictly within the same grade and track."""
    session = get_exam_session_by_id(db, session_id)
    if not session:
        raise ExamSessionNotFoundError(f"Session {session_id} not found.")

    assignments = [a for a in session.assignments if a.student]
    if grade:
        assignments = [a for a in assignments if a.student.grade == str(grade)]
    if track_id:
        assignments = [a for a in assignments if a.student.academic_track_id == track_id]

    results_map = {r.student_id: r for r in session.results}
    rows = []
    group_scores_agg: Dict[str, List[float]] = {}
    valid_ranks = []

    for a in assignments:
        st = a.student
        res = results_map.get(st.id)
        if res:
            res_type = "Tutor-Corrected" if res.is_tutor_corrected else "Student-Entered"
            review_state = "Reviewed" if res.is_reviewed else "Not Reviewed"
            group_scores = {gr.group_title: gr.percentage for gr in res.group_results}
            for title, pct in group_scores.items():
                if title not in group_scores_agg:
                    group_scores_agg[title] = []
                group_scores_agg[title].append(pct)

            avg_pct = round(sum(group_scores.values()) / len(group_scores), 2) if group_scores else None
            if res.overall_rank is not None:
                valid_ranks.append(res.overall_rank)

            rows.append({
                "student_id": str(st.id),
                "name": st.full_name or st.username,
                "grade": st.grade,
                "track": st.academic_track.name if st.academic_track else "",
                "submission_status": "Submitted",
                "result_type": res_type,
                "review_state": review_state,
                "overall_rank": res.overall_rank,
                "average_percentage": avg_pct,
                "group_scores": group_scores,
                "is_late": res.is_late,
            })
        else:
            # Missing result - NEVER treated as zero!
            rows.append({
                "student_id": str(st.id),
                "name": st.full_name or st.username,
                "grade": st.grade,
                "track": st.academic_track.name if st.academic_track else "",
                "submission_status": "Missing",
                "result_type": "N/A",
                "review_state": "N/A",
                "overall_rank": None,
                "average_percentage": None,
                "group_scores": {},
                "is_late": False,
            })

    group_averages = {
        title: round(sum(scores) / len(scores), 2)
        for title, scores in group_scores_agg.items()
        if scores
    }
    avg_rank = round(sum(valid_ranks) / len(valid_ranks), 1) if valid_ranks else None

    return {
        "session": session,
        "filter_grade": grade,
        "filter_track_id": track_id,
        "rows": rows,
        "group_averages": group_averages,
        "average_rank": avg_rank,
        "total_assigned": len(assignments),
        "submitted_count": len([r for r in rows if r["submission_status"] == "Submitted"]),
        "missing_count": len([r for r in rows if r["submission_status"] == "Missing"]),
    }


def get_exam_series_analytics(db: Session, exam_id: uuid.UUID) -> Dict[str, Any]:
    """Analytics for a selected exam series including occurrences, submissions, and averages."""
    exam = get_exam_by_id(db, exam_id)
    if not exam:
        raise ExamNotFoundError(f"Exam series {exam_id} not found.")

    today = today_local()
    total_occurrences = len(exam.sessions)
    completed_occurrences = len([s for s in exam.sessions if s.date < today and s.status == "SCHEDULED"])

    all_results = (
        db.query(StudentExamResult)
        .join(ExamSession, ExamSession.id == StudentExamResult.exam_session_id)
        .options(joinedload(StudentExamResult.group_results))
        .filter(ExamSession.exam_id == exam.id)
        .order_by(ExamSession.date.asc())
        .all()
    )

    total_submitted = len(all_results)
    expected_sessions = [s for s in exam.sessions if s.date <= today and s.status == "SCHEDULED"]
    expected_pairs = {
        (s.id, a.student_id)
        for s in expected_sessions
        for a in s.assignments
    }
    total_expected = len(expected_pairs)
    if total_expected > 0:
        submitted_expected = sum(
            1 for r in all_results if (r.exam_session_id, r.student_id) in expected_pairs
        )
        missing_count = max(0, total_expected - submitted_expected)
        submission_rate = round((submitted_expected / total_expected * 100), 1)
    else:
        missing_count = 0
        submission_rate = 100.0

    group_percentages: Dict[str, List[float]] = {}
    ranks: List[int] = []
    consecutive_comparisons: List[Dict[str, Any]] = []

    # Map session id to results for consecutive comparison
    for s in sorted(exam.sessions, key=lambda x: x.date):
        s_results = [r for r in all_results if r.exam_session_id == s.id]
        if s_results:
            s_pcts = [
                gr.percentage for r in s_results for gr in r.group_results
            ]
            avg_p = round(sum(s_pcts) / len(s_pcts), 2) if s_pcts else 0.0
            consecutive_comparisons.append({
                "session_id": str(s.id),
                "date": s.date.isoformat(),
                "title": s.title or exam.title,
                "submissions": len(s_results),
                "average_percentage": avg_p,
            })

    for r in all_results:
        if r.overall_rank is not None:
            ranks.append(r.overall_rank)
        for gr in r.group_results:
            if gr.group_title not in group_percentages:
                group_percentages[gr.group_title] = []
            group_percentages[gr.group_title].append(gr.percentage)

    reporting_group_averages = {
        title: round(sum(scores) / len(scores), 2)
        for title, scores in group_percentages.items()
        if scores
    }
    avg_rank = round(sum(ranks) / len(ranks), 1) if ranks else None

    return {
        "exam_title": exam.title,
        "total_occurrences": total_occurrences,
        "completed_occurrences": completed_occurrences,
        "total_submitted": total_submitted,
        "missing_submissions": missing_count,
        "submission_rate": submission_rate,
        "reporting_group_averages": reporting_group_averages,
        "average_rank": avg_rank,
        "consecutive_comparisons": consecutive_comparisons,
    }


def get_student_comprehensive_analytics(
    db: Session,
    student_id: uuid.UUID,
    exam_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Calculate deep reporting group analytics, progression trends, and missing exams."""
    student = db.query(User).filter(User.id == student_id, User.role == "STUDENT").first()
    if not student:
        raise ExamValidationError(f"Student {student_id} not found.")

    query = (
        db.query(StudentExamResult)
        .join(ExamSession, ExamSession.id == StudentExamResult.exam_session_id)
        .options(
            joinedload(StudentExamResult.exam_session).joinedload(ExamSession.exam),
            joinedload(StudentExamResult.group_results),
        )
        .filter(StudentExamResult.student_id == student_id)
    )
    if exam_id:
        query = query.filter(ExamSession.exam_id == exam_id)
    results = query.order_by(ExamSession.date.asc()).all()

    rank_progression = []
    group_history: Dict[str, List[float]] = {}
    consecutive_diffs = []
    prev_overall_avg = None

    for r in results:
        sess = r.exam_session
        date_str = sess.date.strftime("%Y-%m-%d")
        exam_title = sess.title or sess.exam.title

        pcts = [gr.percentage for gr in r.group_results]
        overall_avg = round(sum(pcts) / len(pcts), 2) if pcts else None

        if r.overall_rank is not None:
            rank_progression.append({"date": date_str, "exam_title": exam_title, "rank": r.overall_rank})

        for gr in r.group_results:
            if gr.group_title not in group_history:
                group_history[gr.group_title] = []
            group_history[gr.group_title].append(gr.percentage)

        diff = round(overall_avg - prev_overall_avg, 2) if (overall_avg is not None and prev_overall_avg is not None) else None
        consecutive_diffs.append({
            "date": date_str,
            "exam_title": exam_title,
            "average_percentage": overall_avg,
            "change_from_previous": diff,
            "overall_rank": r.overall_rank,
        })
        if overall_avg is not None:
            prev_overall_avg = overall_avg

    # Best, weakest, and trends per group
    group_stats = {}
    for title, scores in group_history.items():
        avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0
        # Avoid claiming trend from only 1 or 2 results: requires >= 3 results
        is_sufficient = len(scores) >= 3
        if is_sufficient:
            recent_delta = scores[-1] - scores[-2]
            trend = "Improving" if recent_delta >= 2.0 else ("Declining" if recent_delta <= -2.0 else "Relatively stable")
        else:
            trend = "Insufficient data"
        group_stats[title] = {
            "average": avg_score,
            "best": max(scores) if scores else 0.0,
            "weakest": min(scores) if scores else 0.0,
            "latest": scores[-1] if scores else 0.0,
            "trend": trend,
            "is_sufficient_data": is_sufficient,
            "scores_count": len(scores),
        }

    # Missing submissions
    today = today_local(getattr(student, "timezone", None))
    assigned_sessions = (
        db.query(ExamSession)
        .join(ExternalExamAssignment, ExternalExamAssignment.exam_session_id == ExamSession.id)
        .options(joinedload(ExamSession.exam))
        .filter(
            ExternalExamAssignment.student_id == student_id,
            ExamSession.date <= today,
            ExamSession.status == "SCHEDULED",
        )
        .all()
    )
    submitted_session_ids = {r.exam_session_id for r in results}
    missing_sessions = [
        {"session_id": str(s.id), "exam_title": s.exam.title if s.exam else "", "date": s.date.isoformat()}
        for s in assigned_sessions if s.id not in submitted_session_ids
    ]

    all_scores = [gr.percentage for r in results for gr in r.group_results]
    overall_mean = round(sum(all_scores) / len(all_scores), 2) if all_scores else None

    # Overall performance trend
    if len(consecutive_diffs) >= 3:
        last_diff = consecutive_diffs[-1]["change_from_previous"]
        if last_diff is not None and last_diff >= 2.0:
            overall_trend = "Improving"
        elif last_diff is not None and last_diff <= -2.0:
            overall_trend = "Declining"
        else:
            overall_trend = "Relatively stable"
    else:
        overall_trend = "Relatively stable"

    return {
        "student": student,
        "results_count": len(results),
        "overall_average": overall_mean,
        "overall_trend": overall_trend,
        "rank_progression": rank_progression,
        "consecutive_comparisons": consecutive_diffs,
        "group_stats": group_stats,
        "missing_sessions": missing_sessions,
    }
