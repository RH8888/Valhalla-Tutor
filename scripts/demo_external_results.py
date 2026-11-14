"""Generate realistic student results and report cards for external exam sessions."""
import json
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.models.exam import (
    ExamSession,
    StudentExamResult,
    StudentExamSubjectResult,
    StudentExamGroupResult,
    ExamAuditLog,
)
from app.models.user import User
from scripts.demo_pdf import save_demo_pdf


def generate_demo_external_results(
    db: Session,
    completed_sessions: list[ExamSession],
    students: list[User],
    tutor: User,
) -> None:
    now = datetime.now(timezone.utc)

    for sess_idx, sess in enumerate(completed_sessions):
        for s_idx, student in enumerate(students):
            # Simulate a missing submission for one low performer on session 2
            if sess_idx == 1 and student.username == "demo_math_11_3":
                continue

            existing = db.query(StudentExamResult).filter(
                StudentExamResult.exam_session_id == sess.id,
                StudentExamResult.student_id == student.id,
            ).first()
            if existing:
                continue

            # Determine performance based on username pattern and session
            is_top = "10_1" in student.username or "11_1" in student.username or "12_1" in student.username
            is_low = "10_2" in student.username and "exp" in student.username or "11_3" in student.username or "12_2" in student.username

            if is_top:
                rank = 5 + (s_idx % 10)
                base_pct = 82.0 + (3.0 if sess_idx == 1 else 0.0)  # improving trend
                reviewed = True
                late = False
            elif is_low:
                rank = 210 + (s_idx * 7)
                base_pct = 28.0 - (2.0 if sess_idx == 1 else 0.0)  # declining/low
                reviewed = False
                late = (s_idx % 2 == 0)
            else:
                rank = 65 + (s_idx * 5)
                base_pct = 54.0 + (1.0 if sess_idx == 1 else 0.0)
                reviewed = (s_idx % 2 == 1)
                late = False

            rel_path, orig_name = save_demo_pdf(
                subfolder="report_cards",
                filename_prefix=f"report_{student.username}_{sess.id.hex[:6]}",
                title=f"کارنامه {sess.title}",
                subtitle=f"دانش‌آموز: {student.full_name} - رتبه: {rank}",
            )

            res = StudentExamResult(
                student_id=student.id,
                exam_session_id=sess.id,
                overall_rank=rank,
                notes=f"کارنامه رسمی دمو برای {student.full_name}",
                report_card_file_path=rel_path,
                report_card_file_name=orig_name,
                grade=student.grade,
                academic_track_id=student.academic_track_id,
                config_snapshot=json.dumps({"grade": student.grade, "track": student.academic_track.name if student.academic_track else ""}),
                is_reviewed=reviewed,
                reviewed_by_id=tutor.id if reviewed else None,
                reviewed_at=now - timedelta(days=2) if reviewed else None,
                is_late=late,
                is_tutor_corrected=(s_idx == 0 and sess_idx == 0),
            )
            db.add(res)
            db.flush()

            # Subject scores
            track_subjects = student.academic_track.subjects if student.academic_track else []
            for sub_i, sub in enumerate(track_subjects):
                variation = ((sub_i * 3) % 9) - 4
                sub_pct = max(5.0, min(98.0, base_pct + variation))
                correct = int(sub_pct * 0.3)
                incorrect = int((100 - sub_pct) * 0.1)
                db.add(StudentExamSubjectResult(
                    student_exam_result_id=res.id,
                    subject_id=sub.id,
                    correct_answers=correct,
                    incorrect_answers=incorrect,
                    percentage=round(sub_pct, 1),
                ))

            # Group score
            db.add(StudentExamGroupResult(
                student_exam_result_id=res.id,
                group_title="مجموعه دروس اختصاصی",
                percentage=round(base_pct, 1),
                included_subject_names="، ".join([s.name for s in track_subjects[:3]]),
            ))

            # Audit log
            db.add(ExamAuditLog(
                actor_id=student.id,
                entity_type="StudentExamResult",
                entity_id=res.id,
                exam_id=sess.exam_id,
                action="SUBMIT_RESULT",
                new_value=json.dumps({"rank": rank, "reviewed": reviewed}),
            ))

    db.flush()
