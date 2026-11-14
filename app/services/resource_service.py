import uuid
from typing import List, Optional
from sqlalchemy.orm import Session

from app.models.course import Course, CourseChapter
from app.models.book import Book, BookChapter
from app.models.subject import Subject


class CourseNotFoundError(Exception):
    pass


class CourseChapterNotFoundError(Exception):
    pass


class BookNotFoundError(Exception):
    pass


class BookChapterNotFoundError(Exception):
    pass


def list_courses(db: Session, subject_id: Optional[uuid.UUID] = None) -> List[Course]:
    query = db.query(Course)
    if subject_id:
        query = query.filter(Course.subject_id == subject_id)
    return query.order_by(Course.teacher_name, Course.name).all()


def get_course_by_id(db: Session, course_id: uuid.UUID) -> Optional[Course]:
    return db.query(Course).filter(Course.id == course_id).first()


def create_course(
    db: Session,
    subject_id: uuid.UUID,
    teacher_name: str,
    name: str,
    grade: str,
    description: Optional[str] = None,
) -> Course:
    subject = db.query(Subject).filter(Subject.id == subject_id).first()
    if not subject:
        raise ValueError(f"Subject with id {subject_id} does not exist.")

    clean_teacher = teacher_name.strip()
    clean_name = name.strip()
    clean_grade = grade.strip()
    if not clean_teacher or not clean_name or not clean_grade:
        raise ValueError("Teacher name, course name, and grade are required.")

    course = Course(
        subject_id=subject_id,
        teacher_name=clean_teacher,
        name=clean_name,
        grade=clean_grade,
        description=description.strip() if description else None,
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


def update_course(
    db: Session,
    course_id: uuid.UUID,
    teacher_name: str,
    name: str,
    grade: str,
    description: Optional[str] = None,
) -> Course:
    course = get_course_by_id(db, course_id)
    if not course:
        raise CourseNotFoundError(f"Course with id {course_id} not found.")

    clean_teacher = teacher_name.strip()
    clean_name = name.strip()
    clean_grade = grade.strip()
    if not clean_teacher or not clean_name or not clean_grade:
        raise ValueError("Teacher name, course name, and grade are required.")

    course.teacher_name = clean_teacher
    course.name = clean_name
    course.grade = clean_grade
    course.description = description.strip() if description else None
    db.commit()
    db.refresh(course)
    return course


def delete_course(db: Session, course_id: uuid.UUID) -> None:
    course = get_course_by_id(db, course_id)
    if not course:
        raise CourseNotFoundError(f"Course with id {course_id} not found.")
    db.delete(course)
    db.commit()


def get_course_chapter_by_id(db: Session, chapter_id: uuid.UUID) -> Optional[CourseChapter]:
    return db.query(CourseChapter).filter(CourseChapter.id == chapter_id).first()


def create_course_chapter(
    db: Session,
    course_id: uuid.UUID,
    name: str,
    video_count: int,
    description: Optional[str] = None,
    display_order: int = 1,
) -> CourseChapter:
    course = get_course_by_id(db, course_id)
    if not course:
        raise CourseNotFoundError(f"Course with id {course_id} not found.")

    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Chapter name cannot be empty.")
    if video_count < 0:
        raise ValueError("Video count cannot be negative.")

    chapter = CourseChapter(
        course_id=course_id,
        name=clean_name,
        video_count=video_count,
        description=description.strip() if description else None,
        display_order=display_order,
    )
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    return chapter


def update_course_chapter(
    db: Session,
    chapter_id: uuid.UUID,
    name: str,
    video_count: int,
    description: Optional[str] = None,
    display_order: Optional[int] = None,
) -> CourseChapter:
    chapter = get_course_chapter_by_id(db, chapter_id)
    if not chapter:
        raise CourseChapterNotFoundError(f"Course chapter with id {chapter_id} not found.")

    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Chapter name cannot be empty.")
    if video_count < 0:
        raise ValueError("Video count cannot be negative.")

    chapter.name = clean_name
    chapter.video_count = video_count
    chapter.description = description.strip() if description else None
    if display_order is not None:
        chapter.display_order = display_order
    db.commit()
    db.refresh(chapter)
    return chapter


def delete_course_chapter(db: Session, chapter_id: uuid.UUID) -> None:
    chapter = get_course_chapter_by_id(db, chapter_id)
    if not chapter:
        raise CourseChapterNotFoundError(f"Course chapter with id {chapter_id} not found.")
    db.delete(chapter)
    db.commit()


def list_books(db: Session, subject_id: Optional[uuid.UUID] = None) -> List[Book]:
    query = db.query(Book)
    if subject_id:
        query = query.filter(Book.subject_id == subject_id)
    return query.order_by(Book.title).all()


def get_book_by_id(db: Session, book_id: uuid.UUID) -> Optional[Book]:
    return db.query(Book).filter(Book.id == book_id).first()


def create_book(
    db: Session,
    subject_id: uuid.UUID,
    title: str,
    grade: str,
    description: Optional[str] = None,
) -> Book:
    subject = db.query(Subject).filter(Subject.id == subject_id).first()
    if not subject:
        raise ValueError(f"Subject with id {subject_id} does not exist.")

    clean_title = title.strip()
    clean_grade = grade.strip()
    if not clean_title or not clean_grade:
        raise ValueError("Book title and grade are required.")

    book = Book(
        subject_id=subject_id,
        title=clean_title,
        grade=clean_grade,
        description=description.strip() if description else None,
    )
    db.add(book)
    db.commit()
    db.refresh(book)
    return book


def update_book(
    db: Session,
    book_id: uuid.UUID,
    title: str,
    grade: str,
    description: Optional[str] = None,
) -> Book:
    book = get_book_by_id(db, book_id)
    if not book:
        raise BookNotFoundError(f"Book with id {book_id} not found.")

    clean_title = title.strip()
    clean_grade = grade.strip()
    if not clean_title or not clean_grade:
        raise ValueError("Book title and grade are required.")

    book.title = clean_title
    book.grade = clean_grade
    book.description = description.strip() if description else None
    db.commit()
    db.refresh(book)
    return book


def delete_book(db: Session, book_id: uuid.UUID) -> None:
    book = get_book_by_id(db, book_id)
    if not book:
        raise BookNotFoundError(f"Book with id {book_id} not found.")
    db.delete(book)
    db.commit()


def get_book_chapter_by_id(db: Session, chapter_id: uuid.UUID) -> Optional[BookChapter]:
    return db.query(BookChapter).filter(BookChapter.id == chapter_id).first()


def create_book_chapter(
    db: Session,
    book_id: uuid.UUID,
    title: str,
    test_count: int,
    description: Optional[str] = None,
    display_order: int = 1,
) -> BookChapter:
    book = get_book_by_id(db, book_id)
    if not book:
        raise BookNotFoundError(f"Book with id {book_id} not found.")

    clean_title = title.strip()
    if not clean_title:
        raise ValueError("Chapter title cannot be empty.")
    if test_count < 0:
        raise ValueError("Test count cannot be negative.")

    chapter = BookChapter(
        book_id=book_id,
        title=clean_title,
        test_count=test_count,
        description=description.strip() if description else None,
        display_order=display_order,
    )
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    return chapter


def update_book_chapter(
    db: Session,
    chapter_id: uuid.UUID,
    title: str,
    test_count: int,
    description: Optional[str] = None,
    display_order: Optional[int] = None,
) -> BookChapter:
    chapter = get_book_chapter_by_id(db, chapter_id)
    if not chapter:
        raise BookChapterNotFoundError(f"Book chapter with id {chapter_id} not found.")

    clean_title = title.strip()
    if not clean_title:
        raise ValueError("Chapter title cannot be empty.")
    if test_count < 0:
        raise ValueError("Test count cannot be negative.")

    chapter.title = clean_title
    chapter.test_count = test_count
    chapter.description = description.strip() if description else None
    if display_order is not None:
        chapter.display_order = display_order
    db.commit()
    db.refresh(chapter)
    return chapter


def delete_book_chapter(db: Session, chapter_id: uuid.UUID) -> None:
    chapter = get_book_chapter_by_id(db, chapter_id)
    if not chapter:
        raise BookChapterNotFoundError(f"Book chapter with id {chapter_id} not found.")
    db.delete(chapter)
    db.commit()



