import pytest
from sqlalchemy.orm import Session

from app.services.academic_service import create_subject, delete_subject, SubjectInUseError
from app.services.resource_service import (
    CourseNotFoundError,
    CourseChapterNotFoundError,
    BookNotFoundError,
    BookChapterNotFoundError,
    create_course,
    create_course_chapter,
    update_course,
    update_course_chapter,
    delete_course,
    delete_course_chapter,
    get_course_by_id,
    get_course_chapter_by_id,
    list_courses,
    create_book,
    create_book_chapter,
    update_book,
    update_book_chapter,
    delete_book,
    delete_book_chapter,
    get_book_by_id,
    get_book_chapter_by_id,
    list_books,
)


def test_course_and_chapters_flow(db_session: Session):
    subject = create_subject(db_session, "فیزیک")

    # 1. Create two courses by different teachers for same subject and grade
    c1 = create_course(
        db_session,
        subject_id=subject.id,
        teacher_name="استاد یحیوی",
        name="فیزیک جامع کنکور",
        grade="دوازدهم",
        description="دوره جامع تستی",
    )
    c2 = create_course(
        db_session,
        subject_id=subject.id,
        teacher_name="استad نوکنده",
        name="فیزیک دوازدهم نهایی",
        grade="دوازدهم",
    )
    assert c1.id != c2.id
    assert len(list_courses(db_session, subject_id=subject.id)) == 2

    # 2. Add chapters with video counts
    ch1 = create_course_chapter(
        db_session,
        course_id=c1.id,
        name="حرکت بر خط راست",
        video_count=12,
        display_order=1,
    )
    ch2 = create_course_chapter(
        db_session,
        course_id=c1.id,
        name="دینامیک",
        video_count=18,
        display_order=2,
    )
    assert ch1.video_count == 12
    assert ch2.video_count == 18

    # 3. Negative video count rejected
    with pytest.raises(ValueError, match="cannot be negative"):
        create_course_chapter(db_session, course_id=c1.id, name="نوسان", video_count=-3)

    # 4. Update chapter
    updated_ch = update_course_chapter(db_session, ch1.id, name="حرکت‌شناسی پیشرفته", video_count=15)
    assert updated_ch.name == "حرکت‌شناسی پیشرفته"
    assert updated_ch.video_count == 15

    # 5. Delete chapter
    delete_course_chapter(db_session, ch2.id)
    assert get_course_chapter_by_id(db_session, ch2.id) is None

    # 6. Delete course cascades to chapters
    delete_course(db_session, c1.id)
    assert get_course_by_id(db_session, c1.id) is None
    assert get_course_chapter_by_id(db_session, ch1.id) is None


def test_book_and_chapters_flow(db_session: Session):
    subject = create_subject(db_session, "شیمی")

    # 1. Create book
    b1 = create_book(
        db_session,
        subject_id=subject.id,
        title="شیمی دوازدهم خیلی سبز",
        grade="دوازدهم",
        description="تست و درسنامه",
    )
    assert b1.id is not None
    assert len(list_books(db_session, subject_id=subject.id)) == 1

    # 2. Add chapters with test counts
    ch1 = create_book_chapter(
        db_session,
        book_id=b1.id,
        title="مولکول‌ها در خدمت تندرستی",
        test_count=240,
        display_order=1,
    )
    ch2 = create_book_chapter(
        db_session,
        book_id=b1.id,
        title="آسایش و رفاه در سایه شیمی",
        test_count=310,
        display_order=2,
    )
    assert ch1.test_count == 240
    assert ch2.test_count == 310

    # 3. Negative test count rejected
    with pytest.raises(ValueError, match="cannot be negative"):
        create_book_chapter(db_session, book_id=b1.id, title="شیمی برتر", test_count=-10)

    # 4. Update book chapter
    updated = update_book_chapter(db_session, ch1.id, title="فصل ۱ شیمی ۱۲", test_count=260)
    assert updated.title == "فصل ۱ شیمی ۱۲"
    assert updated.test_count == 260

    # 5. Delete chapter
    delete_book_chapter(db_session, ch2.id)
    assert get_book_chapter_by_id(db_session, ch2.id) is None

    # 6. Delete book cascades to chapters
    delete_book(db_session, b1.id)
    assert get_book_by_id(db_session, b1.id) is None
    assert get_book_chapter_by_id(db_session, ch1.id) is None


def test_subject_referenced_by_resource_prevents_deletion(db_session: Session):
    subject = create_subject(db_session, "هندسه")
    book = create_book(db_session, subject_id=subject.id, title="هندسه گاج", grade="دهم")

    # Subject deletion should fail because book references it
    with pytest.raises(SubjectInUseError):
        delete_subject(db_session, subject.id)

    # Remove book, now deletion succeeds
    delete_book(db_session, book.id)
    delete_subject(db_session, subject.id)
    assert db_session.query(type(subject)).filter_by(id=subject.id).first() is None

