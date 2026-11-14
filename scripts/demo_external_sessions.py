"""Demo External Exam session occurrences, track configs, and assignments."""
from datetime import date, datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.models.exam import (
    Exam,
    ExamSession,
    ExamSessionAudit,
    ExamTrackConfiguration,
    ExamSubjectConfiguration,
    ExternalExamAssignment,
)
from app.models.track import AcademicTrack
from app.models.user import User


def setup_demo_external_sessions(
    db: Session,
    exam: Exam,
    tracks: dict[str, AcademicTrack],
    students: list[User],
    tutor: User,
) -> list[ExamSession]:
    today = date.today()
    friday_offset = (4 - today.weekday()) % 7

    session_plans = [
        {"title": "آزمون مرحله ۱ قلم‌چی (مهرماه)", "date": today - timedelta(days=28 + (today.weekday() - 4) % 7), "status": "COMPLETED", "seq": 1},
        {"title": "آزمون مرحله ۲ قلم‌چی (آبان‌ماه)", "date": today - timedelta(days=14 + (today.weekday() - 4) % 7), "status": "COMPLETED", "seq": 2},
        {"title": "آزمون مرحله ۳ قلم‌چی (لغو شده)", "date": today - timedelta(days=7 + (today.weekday() - 4) % 7), "status": "SKIPPED", "seq": 3, "skip_reason": "تعطیلی به علت آلودگی هوا"},
        {"title": "آزمون مرحله ۴ قلم‌چی (پیش‌رو)", "date": today + timedelta(days=friday_offset if friday_offset > 0 else 7), "status": "SCHEDULED", "seq": 4},
    ]

    sessions = []
    for plan in session_plans:
        sess = db.query(ExamSession).filter(
            ExamSession.exam_id == exam.id,
            ExamSession.date == plan["date"],
        ).first()
        if not sess:
            deadline = datetime.combine(plan["date"] + timedelta(days=2), datetime.min.time(), tzinfo=timezone.utc)
            sess = ExamSession(
                exam_id=exam.id,
                date=plan["date"],
                title=plan["title"],
                status=plan["status"],
                sequence_order=plan["seq"],
                skip_reason=plan.get("skip_reason"),
                submission_deadline=deadline,
                allow_late_submission=True,
                is_manually_added=False,
            )
            db.add(sess)
            db.flush()

            if plan["status"] == "SKIPPED":
                audit = ExamSessionAudit(
                    exam_session_id=sess.id,
                    actor_id=tutor.id,
                    action="STATUS_CHANGED_TO_SKIPPED",
                    reason=plan.get("skip_reason"),
                )
                db.add(audit)

            # Link track configurations for both tracks
            for trk in tracks.values():
                tc = ExamTrackConfiguration(exam_session_id=sess.id, track_id=trk.id)
                db.add(tc)
                db.flush()
                for sub in trk.subjects:
                    db.add(ExamSubjectConfiguration(exam_track_config_id=tc.id, subject_id=sub.id))

            # Assign to students
            for s in students:
                db.add(ExternalExamAssignment(exam_session_id=sess.id, student_id=s.id))

        sessions.append(sess)

    db.flush()
    return sessions
