"""Curriculum and academic reference records for demo generator."""
import uuid
from sqlalchemy.orm import Session
from app.models.subject import Subject, SubjectGrade
from app.models.track import AcademicTrack
from app.models.course import Course, CourseChapter
from app.models.book import Book, BookChapter

GRADES = ["10", "11", "12"]

MATH_SUBJECTS = ["حسابان", "هندسه", "آمار و احتمال و گسسته", "فیزیک", "شیمی", "عمومی"]
EXP_SUBJECTS = ["زیستشناسی", "فیزیک", "شیمی", "ریاضی", "عمومی"]


def ensure_subject(db: Session, name: str) -> Subject:
    sub = db.query(Subject).filter(Subject.name == name).first()
    if not sub:
        sub = Subject(name=name, description=f"درس {name}")
        for g in GRADES:
            sub.grades_rel.append(SubjectGrade(subject_id=sub.id, grade=g))
        db.add(sub)
        db.flush()
    return sub


def ensure_tracks_and_subjects(db: Session) -> dict[str, AcademicTrack]:
    all_names = set(MATH_SUBJECTS + EXP_SUBJECTS)
    subjects = {name: ensure_subject(db, name) for name in all_names}

    math_track = db.query(AcademicTrack).filter(AcademicTrack.name == "ریاضی").first()
    if not math_track:
        math_track = AcademicTrack(
            name="ریاضی",
            description="رشته علوم ریاضی و فنی",
            is_default=True,
            subjects=[subjects[n] for n in MATH_SUBJECTS],
        )
        db.add(math_track)
        db.flush()

    exp_track = db.query(AcademicTrack).filter(AcademicTrack.name == "تجربی").first()
    if not exp_track:
        exp_track = AcademicTrack(
            name="تجربی",
            description="رشته علوم تجربی",
            is_default=True,
            subjects=[subjects[n] for n in EXP_SUBJECTS],
        )
        db.add(exp_track)
        db.flush()

    return {"ریاضی": math_track, "تجربی": exp_track}


def ensure_demo_curriculum(db: Session) -> None:
    """Ensure sample books and video courses exist for planning."""
    fizik = ensure_subject(db, "فیزیک")
    hesaban = ensure_subject(db, "حسابان")

    # Sample demo book
    book = db.query(Book).filter(Book.title == "[دمو] تست فیزیک جامع خیلی‌سبز").first()
    if not book:
        book = Book(
            subject_id=fizik.id,
            title="[دمو] تست فیزیک جامع خیلی‌سبز",
            grade="11",
            description="کتاب تست فیزیک یازدهم برای تمرین و ارزیابی",
        )
        book.chapters.append(BookChapter(title="فصل اول: الکتریسیته ساکن", test_count=120, display_order=1))
        book.chapters.append(BookChapter(title="فصل دوم: جریان الکتریکی", test_count=95, display_order=2))
        book.chapters.append(BookChapter(title="فصل سوم: مغناطیس", test_count=80, display_order=3))
        db.add(book)

    # Sample demo course
    course = db.query(Course).filter(Course.name == "[دمو] دوره جامع حسابان کنکور").first()
    if not course:
        course = Course(
            subject_id=hesaban.id,
            teacher_name="استاد دمو",
            name="[دمو] دوره جامع حسابان کنکور",
            grade="11",
            description="تدریس کامل مباحث حسابان یازدهم با حل تمرین",
        )
        course.chapters.append(CourseChapter(name="جلسه ۱ تا ۳: تابع و معادلات درجه دو", video_count=6, display_order=1))
        course.chapters.append(CourseChapter(name="جلسه ۴ تا ۶: مثلثات و توابع نمایی", video_count=5, display_order=2))
        db.add(course)

    db.flush()
