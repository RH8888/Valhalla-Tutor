"""Entrypoint for generating or safely cleaning up complete demo data."""
import sys
import argparse
from pathlib import Path

# Ensure project root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole
from scripts.demo_curriculum import ensure_tracks_and_subjects, ensure_demo_curriculum
from scripts.demo_students import ensure_demo_students, DEFAULT_PASSWORD
from scripts.demo_external_series import setup_demo_external_series
from scripts.demo_external_sessions import setup_demo_external_sessions
from scripts.demo_external_results import generate_demo_external_results
from scripts.demo_practice_exams import setup_demo_practice_exams
from scripts.demo_practice_attempts import generate_demo_practice_attempts
from scripts.demo_historical_exams import generate_demo_historical_exams
from scripts.demo_cleanup import cleanup_demo_data


def run_generator() -> None:
    db = SessionLocal()
    try:
        print("\n🚀 [1/6] Initializing Curriculum & Tracks...")
        tracks = ensure_tracks_and_subjects(db)
        ensure_demo_curriculum(db)

        # Get or identify active tutor
        tutor = db.query(User).filter(User.role == UserRole.TUTOR).first()
        if not tutor:
            tutor = User(
                username="headtutor",
                full_name="مشاور ارشد",
                email="headtutor@valhalla.test",
                hashed_password=hash_password(DEFAULT_PASSWORD),
                role=UserRole.TUTOR,
                is_active=True,
            )
            db.add(tutor)
            db.flush()

        print("👥 [2/6] Generating Demo Students (Grades 10, 11, 12)...")
        students = ensure_demo_students(db, tracks)
        print(f"   Created/Verified {len(students)} demo students with password '{DEFAULT_PASSWORD}'")

        print("📝 [3/6] Configuring External Exam Series & Occurrences...")
        exams_dict = setup_demo_external_series(db, tracks, students, tutor)
        ghalamchi = exams_dict["ghalamchi"]
        sessions = setup_demo_external_sessions(db, ghalamchi, tracks, students, tutor)
        completed_sessions = [s for s in sessions if s.status == "COMPLETED"]

        print("📊 [4/6] Generating External Exam Results & Report Card PDFs...")
        generate_demo_external_results(db, completed_sessions, students, tutor)

        print("⏱️ [5/6] Generating Practice Exams, Booklets & Attempts...")
        practice_exams = setup_demo_practice_exams(db, tracks, students)
        generate_demo_practice_attempts(db, practice_exams, students)

        print("📜 [6/6] Generating Historical Exam Records & Attachments...")
        generate_demo_historical_exams(db, students)

        db.commit()
        print("\n✅ Demo dataset generation completed successfully!")
        print("   - All records are tagged with [دمو] or demo_ prefix.")
        print(f"   - Students login format: demo_math_11_1 / {DEFAULT_PASSWORD}")
    except Exception as exc:
        db.rollback()
        print(f"\n❌ Error generating demo data: {exc}")
        raise
    finally:
        db.close()


def run_cleanup() -> None:
    db = SessionLocal()
    try:
        print("\n🧹 Cleaning up demo dataset...")
        counts = cleanup_demo_data(db)
        print("✅ Cleanup complete! Removed records:")
        for k, v in counts.items():
            print(f"   - {k}: {v}")
    except Exception as exc:
        db.rollback()
        print(f"\n❌ Error cleaning demo data: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Valhalla Tutor Demo Database Generator")
    parser.add_argument("--clean", action="store_true", help="Delete ONLY demo records and demo files")
    args = parser.parse_args()

    if args.clean:
        run_cleanup()
    else:
        run_generator()
