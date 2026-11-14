"""Generate demo historical exam records and report cards."""
from datetime import date, timedelta
from sqlalchemy.orm import Session
from app.models.exam import HistoricalExamResult, HistoricalExamSubjectResult
from app.models.user import User
from scripts.demo_pdf import save_demo_pdf


def generate_demo_historical_exams(db: Session, students: list[User]) -> None:
    """Generate historical exam records from previous school years for 11th and 12th graders."""
    # Target students in grades 11 and 12
    senior_students = [s for s in students if s.grade in ["11", "12"]]

    for s_idx, student in enumerate(senior_students):
        past_grade = "10" if student.grade == "11" else "11"
        exam_name = f"[دمو] کنکور آزمایشی جامع سال گذشته - پایه {past_grade}"
        exam_date = date.today() - timedelta(days=365 - (s_idx * 14))

        existing = db.query(HistoricalExamResult).filter(
            HistoricalExamResult.student_id == student.id,
            HistoricalExamResult.exam_name == exam_name,
        ).first()
        if existing:
            continue

        is_top = "top" in student.username or "_1" in student.username
        rank = 12 + (s_idx * 3) if is_top else 130 + (s_idx * 15)
        base_pct = 85.0 if is_top else 48.0

        rel_path, orig_name = save_demo_pdf(
            subfolder="report_cards",
            filename_prefix=f"hist_report_{student.username}",
            title=f"کارنامه سوابق آزمون - پایه {past_grade}",
            subtitle=f"دانش‌آموز: {student.full_name} - تاریخ: {exam_date}",
        )

        hist = HistoricalExamResult(
            student_id=student.id,
            exam_name=exam_name,
            exam_date=exam_date,
            grade=past_grade,
            academic_track_id=student.academic_track_id,
            overall_rank=rank,
            notes=f"سوابق آزمون‌های سال تحصیلی گذشته ثبت شده توسط مشاور برای {student.full_name}",
            report_card_file_path=rel_path,
            report_card_file_name=orig_name,
        )
        db.add(hist)
        db.flush()

        # Subject results
        subject_names = ["ریاضی / حسابان", "فیزیک", "شیمی", "زیست / هندسه", "دروس عمومی"]
        for i, sub_name in enumerate(subject_names):
            variation = ((i * 4) % 10) - 5
            sub_pct = max(10.0, min(96.0, base_pct + variation))
            db.add(HistoricalExamSubjectResult(
                historical_exam_result_id=hist.id,
                subject_name=sub_name,
                percentage=round(sub_pct, 1),
            ))

    db.flush()
