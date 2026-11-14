import pytest
import uuid
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.services.user_service import create_student
from app.services.academic_service import (
    SubjectInUseError,
    TrackInUseError,
    add_subject_to_track,
    assign_student_track,
    create_subject,
    create_track,
    customize_student_subjects,
    delete_subject,
    delete_track,
    get_student_effective_subjects,
    remove_subject_from_track,
    reset_student_subjects_to_track,
    seed_default_academic_data,
    update_subject,
    update_track,
)
from app.services.resource_service import (
    create_book,
    create_book_chapter,
    create_course,
    create_course_chapter,
    delete_book,
    delete_course,
    list_books,
    list_courses,
    update_book_chapter,
    update_course_chapter,
)


def test_seed_and_defaults_are_editable(db_session: Session):
    seed_default_academic_data(db_session)
    from app.services.academic_service import get_track_by_name

    math_track = get_track_by_name(db_session, "ریاضی")
    assert math_track is not None
    assert math_track.is_default is True

    # Defaults are editable! Add a new elective subject to default math track
    new_sub = create_subject(db_session, "المپیاد کامپیوتر")
    add_subject_to_track(db_session, math_track.id, new_sub.id)
    db_session.refresh(math_track)
    assert any(s.name == "المپیاد کامپیوتر" for s in math_track.subjects)

    # Remove a subject from default math track
    remove_subject_from_track(db_session, math_track.id, new_sub.id)
    db_session.refresh(math_track)
    assert not any(s.name == "المپیاد کامپیوتر" for s in math_track.subjects)


def test_student_track_and_customization_isolation(db_session: Session):
    sub1 = create_subject(db_session, "حسابان ۱")
    sub2 = create_subject(db_session, "فیزیک ۱")
    sub3 = create_subject(db_session, "شیمی ۱")
    track = create_track(db_session, "ریاضی یازدهم", subject_ids=[sub1.id, sub2.id])

    student1 = create_student(db_session, full_name="Student One", username="s1", password="PassWord123!")
    student2 = create_student(db_session, full_name="Student Two", username="s2", password="PassWord123!")

    # Both assigned to track
    assign_student_track(db_session, student1.id, track.id)
    assign_student_track(db_session, student2.id, track.id)
    db_session.refresh(student1)
    db_session.refresh(student2)

    assert student1.is_subjects_customized is False
    assert student2.is_subjects_customized is False

    # Customize student1 only
    customize_student_subjects(db_session, student1.id, [sub1.id, sub3.id])
    db_session.refresh(student1)
    db_session.refresh(student2)

    assert student1.is_subjects_customized is True
    assert student2.is_subjects_customized is False

    # Now mutate the shared track (add sub3)
    add_subject_to_track(db_session, track.id, sub3.id)
    db_session.refresh(student1)
    db_session.refresh(student2)

    # student2 automatically reflects track change (now has sub1, sub2, sub3)
    s2_subs = {s.name for s in get_student_effective_subjects(student2)}
    assert s2_subs == {"حسابان ۱", "فیزیک ۱", "شیمی ۱"}

    # student1's custom subjects remain completely isolated (sub1 and sub3 only)
    s1_subs = {s.name for s in get_student_effective_subjects(student1)}
    assert s1_subs == {"حسابان ۱", "شیمی ۱"}


def test_learning_resources_hierarchy_and_non_negative_counts(db_session: Session):
    sub = create_subject(db_session, "زیست‌شناسی")

    # 1. Video Hierarchy: Subject -> Teacher -> Course -> Chapter
    c = create_course(db_session, subject_id=sub.id, teacher_name="دکتر عمارلو", name="زیست جامع", grade="دوازدهم")
    ch_v = create_course_chapter(db_session, course_id=c.id, name="فصل ۱: مولکول‌های اطلاعاتی", video_count=8)
    assert ch_v.video_count == 8

    # Non-negative validation for videos
    with pytest.raises(ValueError, match="cannot be negative"):
        create_course_chapter(db_session, course_id=c.id, name="فصل منفی", video_count=-1)

    with pytest.raises(ValueError, match="cannot be negative"):
        update_course_chapter(db_session, ch_v.id, name=ch_v.name, video_count=-5)

    # 2. Book Hierarchy: Subject -> Book -> Chapter
    b = create_book(db_session, subject_id=sub.id, title="زیست الگو", grade="دوازدهم")
    ch_b = create_book_chapter(db_session, book_id=b.id, title="آزمون جامع فصل ۱", test_count=180)
    assert ch_b.test_count == 180

    # Non-negative validation for tests
    with pytest.raises(ValueError, match="cannot be negative"):
        create_book_chapter(db_session, book_id=b.id, title="تست منفی", test_count=-10)

    with pytest.raises(ValueError, match="cannot be negative"):
        update_book_chapter(db_session, ch_b.id, title=ch_b.title, test_count=-2)

    # Verify chapters are completely separate models
    assert type(ch_v) != type(ch_b)
    assert ch_v.course_id == c.id
    assert ch_b.book_id == b.id


def test_prevention_of_unsafe_deletions(db_session: Session):
    sub = create_subject(db_session, "شیمی پایه")
    c = create_course(db_session, subject_id=sub.id, teacher_name="استاد بهمنی", name="شیمی ۱۰", grade="دهم")

    # Cannot delete subject when course references it
    with pytest.raises(SubjectInUseError, match="referenced by 1 video course"):
        delete_subject(db_session, sub.id)

    delete_course(db_session, c.id)

    b = create_book(db_session, subject_id=sub.id, title="شیمی مبتکران", grade="دهم")
    # Cannot delete subject when book references it
    with pytest.raises(SubjectInUseError, match="referenced by 1 test book"):
        delete_subject(db_session, sub.id)

    delete_book(db_session, b.id)

    # Now subject can be deleted safely
    delete_subject(db_session, sub.id)
    assert db_session.query(type(sub)).filter_by(id=sub.id).first() is None


def test_tutor_and_student_role_authorization_guarantees(db_session: Session):
    from fastapi import HTTPException
    from app.core.dependencies import require_tutor, require_student

    tutor = User(username="tutor1", full_name="Tutor", hashed_password="pw", role=UserRole.TUTOR)
    student = User(username="student1", full_name="Student", hashed_password="pw", role=UserRole.STUDENT)

    # 1. Tutor access check
    assert require_tutor(tutor) == tutor
    with pytest.raises(HTTPException) as exc_info:
        require_tutor(student)
    assert exc_info.value.status_code == 403

    # 2. Student access check
    assert require_student(student) == student
    with pytest.raises(HTTPException) as exc_info:
        require_student(tutor)
    assert exc_info.value.status_code == 403


