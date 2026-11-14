"""Demo External Exam series, configs, and recurring occurrences."""
import uuid
from datetime import date, timedelta
from sqlalchemy.orm import Session
from app.models.exam import (
    Exam,
    ExamGradeTrackConfig,
    ExamReportingGroup,
    ExamReportingGroupSubject,
    ExamSeriesAssignment,
    ExamSession,
    ExamSessionAudit,
    ExamTrackConfiguration,
    ExamSubjectConfiguration,
    ExternalExamAssignment,
)
from app.models.track import AcademicTrack
from app.models.user import User


def setup_demo_external_series(
    db: Session,
    tracks: dict[str, AcademicTrack],
    students: list[User],
    tutor: User,
) -> dict[str, Exam]:
    """Create external exam series and configure grade-track and reporting groups."""
    math_track = tracks["ریاضی"]
    exp_track = tracks["تجربی"]

    exam = db.query(Exam).filter(Exam.title == "[دمو] آزمون‌های دوره‌ای قلم‌چی").first()
    if not exam:
        exam = Exam(
            title="[دمو] آزمون‌های دوره‌ای قلم‌چی",
            description="آزمون‌های برنامه‌ای قلم‌چی برای پایه‌های دهم، یازدهم و دوازدهم",
            is_active=True,
            first_exam_date=date.today() - timedelta(days=60),
            last_exam_date=date.today() + timedelta(days=120),
            recurrence_interval_weeks=2,
            recurrence_weekday=4,  # Friday
            submission_days_after_exam=2,
        )
        db.add(exam)
        db.flush()

    # Configure grade-track configs if missing
    for grade in ["10", "11", "12"]:
        for trk in [math_track, exp_track]:
            cfg = db.query(ExamGradeTrackConfig).filter(
                ExamGradeTrackConfig.exam_id == exam.id,
                ExamGradeTrackConfig.grade == grade,
                ExamGradeTrackConfig.track_id == trk.id,
            ).first()
            if not cfg:
                cfg = ExamGradeTrackConfig(exam_id=exam.id, grade=grade, track_id=trk.id)
                db.add(cfg)
                db.flush()

                # Add a reporting group
                title = "مجموعه ریاضی و علوم" if trk.name == "ریاضی" else "مجموعه زیست و علوم"
                rg = ExamReportingGroup(exam_grade_track_config_id=cfg.id, title=title, order_index=1)
                db.add(rg)
                db.flush()
                for sub in trk.subjects[:3]:
                    db.add(ExamReportingGroupSubject(group_id=rg.id, subject_id=sub.id))

    # Assign series to demo students
    for s in students:
        existing = db.query(ExamSeriesAssignment).filter(
            ExamSeriesAssignment.exam_id == exam.id,
            ExamSeriesAssignment.student_id == s.id,
        ).first()
        if not existing:
            db.add(ExamSeriesAssignment(exam_id=exam.id, student_id=s.id))

    db.flush()
    return {"ghalamchi": exam}
