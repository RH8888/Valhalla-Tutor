"""Safe cleanup function that removes ONLY demo records and demo files."""
import glob
from pathlib import Path
from sqlalchemy.orm import Session
from app.core.storage import get_upload_base_path
from app.models.user import User
from app.models.exam import Exam, HistoricalExamResult, StudentExamResult, ExamAuditLog
from app.models.practice_exam import PracticeExam, StudentPracticeAttempt
from app.models.course import Course
from app.models.book import Book


def cleanup_demo_data(db: Session) -> dict[str, int]:
    """Safely delete all demo-tagged records and files without touching real data."""
    counts = {}

    # 1. Demo Student Practice Attempts
    demo_attempts = (
        db.query(StudentPracticeAttempt)
        .join(User, StudentPracticeAttempt.student_id == User.id)
        .filter(User.username.startswith("demo_"))
        .all()
    )
    counts["practice_attempts"] = len(demo_attempts)
    for att in demo_attempts:
        db.delete(att)
    db.flush()

    # 2. Demo Practice Exams
    demo_practice = db.query(PracticeExam).filter(PracticeExam.title.startswith("[دمو]")).all()
    counts["practice_exams"] = len(demo_practice)
    for p in demo_practice:
        db.delete(p)
    db.flush()

    # 3. Demo External Exam Results & Sessions & Exams
    demo_exam_results = (
        db.query(StudentExamResult)
        .join(User, StudentExamResult.student_id == User.id)
        .filter(User.username.startswith("demo_"))
        .all()
    )
    counts["exam_results"] = len(demo_exam_results)
    for r in demo_exam_results:
        db.delete(r)
    db.flush()

    demo_exams = db.query(Exam).filter(Exam.title.startswith("[دمو]")).all()
    counts["exams"] = len(demo_exams)
    for e in demo_exams:
        # Also clean audit logs for this exam
        db.query(ExamAuditLog).filter(ExamAuditLog.exam_id == e.id).delete(synchronize_session=False)
        db.delete(e)
    db.flush()

    # 4. Demo Historical Exams
    demo_hist = (
        db.query(HistoricalExamResult)
        .join(User, HistoricalExamResult.student_id == User.id)
        .filter(User.username.startswith("demo_"))
        .all()
    )
    counts["historical_exams"] = len(demo_hist)
    for h in demo_hist:
        db.delete(h)
    db.flush()

    # 5. Demo Courses and Books
    demo_courses = db.query(Course).filter(Course.name.startswith("[دمو]")).all()
    counts["courses"] = len(demo_courses)
    for c in demo_courses:
        db.delete(c)
    demo_books = db.query(Book).filter(Book.title.startswith("[دمو]")).all()
    counts["books"] = len(demo_books)
    for b in demo_books:
        db.delete(b)
    db.flush()

    # 6. Demo Users
    demo_users = db.query(User).filter(User.username.startswith("demo_")).all()
    counts["students"] = len(demo_users)
    for u in demo_users:
        db.delete(u)
    db.flush()

    # 7. Demo PDF Files on disk
    upload_base = get_upload_base_path()
    removed_files = 0
    for p in upload_base.glob("**/demo_*.pdf"):
        try:
            p.unlink()
            removed_files += 1
        except Exception:
            pass
    counts["files_removed"] = removed_files

    db.commit()
    return counts
