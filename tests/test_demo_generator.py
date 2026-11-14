"""Test demo generator script and cleanup functionality."""
from app.core.database import SessionLocal
from app.models.user import User
from app.models.exam import Exam, StudentExamResult, HistoricalExamResult
from app.models.practice_exam import PracticeExam, StudentPracticeAttempt
from scripts.generate_demo_data import run_generator, run_cleanup


def test_demo_generator_and_cleanup_lifecycle():
    # 1. Run generation
    run_generator()

    db = SessionLocal()
    try:
        # Verify students
        demo_students = db.query(User).filter(User.username.startswith("demo_")).all()
        assert len(demo_students) >= 12
        assert any(s.grade == "10" for s in demo_students)
        assert any(s.grade == "11" for s in demo_students)
        assert any(s.grade == "12" for s in demo_students)

        # Verify external exams & results
        demo_exams = db.query(Exam).filter(Exam.title.startswith("[دمو]")).all()
        assert len(demo_exams) >= 1
        results = db.query(StudentExamResult).all()
        assert len(results) > 0
        assert any(r.is_reviewed for r in results)
        assert any(r.is_late for r in results)

        # Verify practice exams & attempts
        practice_exams = db.query(PracticeExam).filter(PracticeExam.title.startswith("[دمو]")).all()
        assert len(practice_exams) >= 2
        for pe in practice_exams:
            assert len(pe.booklets) >= 2
            assert len(pe.questions) >= 20

        attempts = db.query(StudentPracticeAttempt).all()
        assert len(attempts) > 0
        assert any(a.status == "COMPLETED" for a in attempts)
        assert any(a.status == "IN_PROGRESS" for a in attempts)

        # Verify historical results
        hist_results = db.query(HistoricalExamResult).all()
        assert len(hist_results) > 0
        assert all(h.report_card_file_path is not None for h in hist_results)
    finally:
        db.close()

    # 2. Run again to ensure idempotency
    run_generator()

    # 3. Clean up and verify removal of demo data only
    run_cleanup()

    db = SessionLocal()
    try:
        assert db.query(User).filter(User.username.startswith("demo_")).count() == 0
        assert db.query(Exam).filter(Exam.title.startswith("[دمو]")).count() == 0
        assert db.query(PracticeExam).filter(PracticeExam.title.startswith("[دمو]")).count() == 0
        assert db.query(HistoricalExamResult).filter(HistoricalExamResult.exam_name.startswith("[دمو]")).count() == 0
    finally:
        db.close()

    # 4. Re-generate so the user has the demo database ready to test
    run_generator()
