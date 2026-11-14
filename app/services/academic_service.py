import uuid
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.subject import Subject, SubjectGrade
from app.models.track import AcademicTrack, track_subjects, student_custom_subjects
from app.models.course import Course
from app.models.book import Book
from app.models.user import User

SUPPORTED_GRADES = ["10", "11", "12"]


class SubjectAlreadyExistsError(Exception):
    pass


class SubjectNotFoundError(Exception):
    pass


class SubjectInUseError(Exception):
    pass


class TrackAlreadyExistsError(Exception):
    pass


class TrackNotFoundError(Exception):
    pass


class TrackInUseError(Exception):
    pass


DEFAULT_MATH_SUBJECTS = ["حسابان", "فیزیک", "شیمی", "هندسه", "آمار و احتمال و گسسته", "عمومی"]
DEFAULT_EXP_SUBJECTS = ["زیستشناسی", "فیزیک", "شیمی", "ریاضی", "عمومی"]


def get_subject_by_id(db: Session, subject_id: uuid.UUID) -> Optional[Subject]:
    return db.query(Subject).filter(Subject.id == subject_id).first()


def get_subject_by_name(db: Session, name: str) -> Optional[Subject]:
    return db.query(Subject).filter(Subject.name == name.strip()).first()


def list_subjects(db: Session) -> List[Subject]:
    return db.query(Subject).order_by(Subject.name).all()


def create_subject(
    db: Session,
    name: str,
    description: Optional[str] = None,
    grades: Optional[List[str]] = None,
) -> Subject:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Subject name cannot be empty.")
    if get_subject_by_name(db, clean_name):
        raise SubjectAlreadyExistsError(f"Subject '{clean_name}' already exists.")

    selected_grades = grades if grades is not None else list(SUPPORTED_GRADES)
    clean_grades = sorted(set(str(x).strip() for x in selected_grades if str(x).strip()))
    if not clean_grades:
        raise ValueError("At least one grade must be configured for the subject.")

    subject = Subject(
        name=clean_name,
        description=description.strip() if description else None,
    )
    for g in clean_grades:
        subject.grades_rel.append(SubjectGrade(subject_id=subject.id, grade=g))

    db.add(subject)
    db.commit()
    db.refresh(subject)
    return subject


def update_subject(
    db: Session,
    subject_id: uuid.UUID,
    name: str,
    description: Optional[str] = None,
    grades: Optional[List[str]] = None,
) -> Subject:
    subject = get_subject_by_id(db, subject_id)
    if not subject:
        raise SubjectNotFoundError(f"Subject with id {subject_id} not found.")

    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Subject name cannot be empty.")

    existing = get_subject_by_name(db, clean_name)
    if existing and existing.id != subject.id:
        raise SubjectAlreadyExistsError(f"Subject '{clean_name}' already exists.")

    subject.name = clean_name
    subject.description = description.strip() if description else None

    if grades is not None:
        clean_grades = sorted(set(str(x).strip() for x in grades if str(x).strip()))
        if not clean_grades:
            raise ValueError("At least one grade must be configured for the subject.")
        subject.grades_rel.clear()
        for g in clean_grades:
            subject.grades_rel.append(SubjectGrade(subject_id=subject.id, grade=g))

    db.commit()
    db.refresh(subject)
    return subject


def delete_subject(db: Session, subject_id: uuid.UUID) -> None:
    subject = get_subject_by_id(db, subject_id)
    if not subject:
        raise SubjectNotFoundError(f"Subject with id {subject_id} not found.")

    # Check references in courses
    course_count = db.query(Course).filter(Course.subject_id == subject_id).count()
    if course_count > 0:
        raise SubjectInUseError(f"Subject '{subject.name}' is referenced by {course_count} video course(s).")

    # Check references in books
    book_count = db.query(Book).filter(Book.subject_id == subject_id).count()
    if book_count > 0:
        raise SubjectInUseError(f"Subject '{subject.name}' is referenced by {book_count} test book(s).")

    # Check references in track_subjects
    track_count = db.execute(
        select(track_subjects).where(track_subjects.c.subject_id == subject_id)
    ).fetchall()
    if track_count:
        raise SubjectInUseError(f"Subject '{subject.name}' is referenced by {len(track_count)} academic track(s).")

    # Check references in student_custom_subjects
    student_count = db.execute(
        select(student_custom_subjects).where(student_custom_subjects.c.subject_id == subject_id)
    ).fetchall()
    if student_count:
        raise SubjectInUseError(f"Subject '{subject.name}' is referenced by {len(student_count)} student customization(s).")

    db.delete(subject)
    db.commit()


def seed_default_academic_data(db: Session) -> None:
    # 1. Seed all default subjects
    all_subject_names = set(DEFAULT_MATH_SUBJECTS + DEFAULT_EXP_SUBJECTS)
    subjects_by_name = {}
    for name in all_subject_names:
        sub = get_subject_by_name(db, name)
        if not sub:
            sub = Subject(name=name)
            for g in SUPPORTED_GRADES:
                sub.grades_rel.append(SubjectGrade(subject_id=sub.id, grade=g))
            db.add(sub)
            db.flush()
        elif not sub.grades_rel:
            for g in SUPPORTED_GRADES:
                sub.grades_rel.append(SubjectGrade(subject_id=sub.id, grade=g))
            db.flush()
        subjects_by_name[name] = sub

    # 2. Seed Mathematics track
    math_track = db.query(AcademicTrack).filter(AcademicTrack.name == "ریاضی").first()
    if not math_track:
        math_track = AcademicTrack(
            name="ریاضی",
            description="رشته علوم ریاضی و فنی",
            is_default=True,
            subjects=[subjects_by_name[name] for name in DEFAULT_MATH_SUBJECTS],
        )
        db.add(math_track)

    # 3. Seed Experimental Sciences track
    exp_track = db.query(AcademicTrack).filter(AcademicTrack.name == "تجربی").first()
    if not exp_track:
        exp_track = AcademicTrack(
            name="تجربی",
            description="رشته علوم تجربی",
            is_default=True,
            subjects=[subjects_by_name[name] for name in DEFAULT_EXP_SUBJECTS],
        )
        db.add(exp_track)

    db.commit()


def get_track_by_id(db: Session, track_id: uuid.UUID) -> Optional[AcademicTrack]:
    return db.query(AcademicTrack).filter(AcademicTrack.id == track_id).first()


def get_track_by_name(db: Session, name: str) -> Optional[AcademicTrack]:
    return db.query(AcademicTrack).filter(AcademicTrack.name == name.strip()).first()


def list_tracks(db: Session) -> List[AcademicTrack]:
    return db.query(AcademicTrack).order_by(AcademicTrack.is_default.desc(), AcademicTrack.name).all()


def create_track(
    db: Session,
    name: str,
    description: Optional[str] = None,
    subject_ids: Optional[List[uuid.UUID]] = None,
    is_default: bool = False,
) -> AcademicTrack:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Track name cannot be empty.")
    if get_track_by_name(db, clean_name):
        raise TrackAlreadyExistsError(f"Academic track '{clean_name}' already exists.")

    track = AcademicTrack(
        name=clean_name,
        description=description.strip() if description else None,
        is_default=is_default,
    )
    if subject_ids:
        subjects = db.query(Subject).filter(Subject.id.in_(subject_ids)).all()
        track.subjects = subjects

    db.add(track)
    db.commit()
    db.refresh(track)
    return track


def update_track(
    db: Session,
    track_id: uuid.UUID,
    name: str,
    description: Optional[str] = None,
) -> AcademicTrack:
    track = get_track_by_id(db, track_id)
    if not track:
        raise TrackNotFoundError(f"Academic track with id {track_id} not found.")

    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Track name cannot be empty.")

    existing = get_track_by_name(db, clean_name)
    if existing and existing.id != track.id:
        raise TrackAlreadyExistsError(f"Academic track '{clean_name}' already exists.")

    track.name = clean_name
    track.description = description.strip() if description else None
    db.commit()
    db.refresh(track)
    return track


def add_subject_to_track(db: Session, track_id: uuid.UUID, subject_id: uuid.UUID) -> AcademicTrack:
    track = get_track_by_id(db, track_id)
    if not track:
        raise TrackNotFoundError(f"Academic track with id {track_id} not found.")
    subject = get_subject_by_id(db, subject_id)
    if not subject:
        raise SubjectNotFoundError(f"Subject with id {subject_id} not found.")

    if subject not in track.subjects:
        track.subjects.append(subject)
        db.commit()
        db.refresh(track)
    return track


def remove_subject_from_track(db: Session, track_id: uuid.UUID, subject_id: uuid.UUID) -> AcademicTrack:
    track = get_track_by_id(db, track_id)
    if not track:
        raise TrackNotFoundError(f"Academic track with id {track_id} not found.")
    subject = get_subject_by_id(db, subject_id)
    if not subject:
        raise SubjectNotFoundError(f"Subject with id {subject_id} not found.")

    if subject in track.subjects:
        track.subjects.remove(subject)
        db.commit()
        db.refresh(track)
    return track


def set_track_subjects(db: Session, track_id: uuid.UUID, subject_ids: List[uuid.UUID]) -> AcademicTrack:
    track = get_track_by_id(db, track_id)
    if not track:
        raise TrackNotFoundError(f"Academic track with id {track_id} not found.")

    subjects = db.query(Subject).filter(Subject.id.in_(subject_ids)).all() if subject_ids else []
    track.subjects = subjects
    db.commit()
    db.refresh(track)
    return track


def delete_track(db: Session, track_id: uuid.UUID) -> None:
    track = get_track_by_id(db, track_id)
    if not track:
        raise TrackNotFoundError(f"Academic track with id {track_id} not found.")

    # Check if students are assigned to this track
    assigned_count = db.query(User).filter(User.academic_track_id == track_id).count()
    if assigned_count > 0:
        raise TrackInUseError(f"Cannot delete track '{track.name}' because {assigned_count} student(s) are assigned to it.")

    db.delete(track)
    db.commit()


def assign_student_track(db: Session, student_id: uuid.UUID, track_id: Optional[uuid.UUID]) -> User:
    student = db.query(User).filter(User.id == student_id).first()
    if not student:
        raise ValueError(f"Student with id {student_id} not found.")

    if track_id is not None:
        track = get_track_by_id(db, track_id)
        if not track:
            raise TrackNotFoundError(f"Academic track with id {track_id} not found.")
        student.academic_track_id = track.id
    else:
        student.academic_track_id = None

    db.commit()
    db.refresh(student)
    return student


def customize_student_subjects(db: Session, student_id: uuid.UUID, subject_ids: List[uuid.UUID]) -> User:
    student = db.query(User).filter(User.id == student_id).first()
    if not student:
        raise ValueError(f"Student with id {student_id} not found.")

    subjects = db.query(Subject).filter(Subject.id.in_(subject_ids)).all() if subject_ids else []
    student.custom_subjects = subjects
    student.is_subjects_customized = True
    db.commit()
    db.refresh(student)
    return student


def reset_student_subjects_to_track(db: Session, student_id: uuid.UUID) -> User:
    student = db.query(User).filter(User.id == student_id).first()
    if not student:
        raise ValueError(f"Student with id {student_id} not found.")

    student.custom_subjects = []
    student.is_subjects_customized = False
    db.commit()
    db.refresh(student)
    return student


def get_student_effective_subjects(student: User) -> List[Subject]:
    if student.is_subjects_customized:
        return list(student.custom_subjects)
    if student.academic_track:
        return list(student.academic_track.subjects)
    return []




