import pytest
import uuid
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.user_service import create_student
from app.services.academic_service import (
    DEFAULT_MATH_SUBJECTS,
    DEFAULT_EXP_SUBJECTS,
    SubjectAlreadyExistsError,
    SubjectInUseError,
    SubjectNotFoundError,
    TrackAlreadyExistsError,
    TrackInUseError,
    TrackNotFoundError,
    add_subject_to_track,
    assign_student_track,
    create_subject,
    create_track,
    customize_student_subjects,
    delete_subject,
    delete_track,
    get_student_effective_subjects,
    get_subject_by_id,
    get_track_by_id,
    list_subjects,
    list_tracks,
    remove_subject_from_track,
    reset_student_subjects_to_track,
    seed_default_academic_data,
    update_subject,
    update_track,
)


def test_seed_default_academic_data(db_session: Session):
    seed_default_academic_data(db_session)

    # Verify subjects exist
    subjects = list_subjects(db_session)
    subject_names = {s.name for s in subjects}
    for sub in DEFAULT_MATH_SUBJECTS + DEFAULT_EXP_SUBJECTS:
        assert sub in subject_names

    # Verify tracks exist
    tracks = list_tracks(db_session)
    track_names = {t.name for t in tracks}
    assert "ریاضی" in track_names
    assert "تجربی" in track_names

    # Verify track subjects
    math_track = next(t for t in tracks if t.name == "ریاضی")
    assert math_track.is_default is True
    math_sub_names = {s.name for s in math_track.subjects}
    for sub in DEFAULT_MATH_SUBJECTS:
        assert sub in math_sub_names


def test_subject_crud_and_validation(db_session: Session):
    # 1. Create subject
    subject = create_subject(db_session, "فیزیک پیشرفته", "توضیحات فیزیک")
    assert subject.id is not None
    assert subject.name == "فیزیک پیشرفته"
    assert subject.description == "توضیحات فیزیک"

    # 2. Duplicate rejection
    with pytest.raises(SubjectAlreadyExistsError):
        create_subject(db_session, "فیزیک پیشرفته")

    # 3. Empty name rejection
    with pytest.raises(ValueError):
        create_subject(db_session, "   ")

    # 4. Update
    updated = update_subject(db_session, subject.id, "فیزیک ۲", "توضیح جدید")
    assert updated.name == "فیزیک ۲"

    # 5. Delete
    delete_subject(db_session, subject.id)
    assert get_subject_by_id(db_session, subject.id) is None


def test_track_crud_and_subject_manipulation(db_session: Session):
    s1 = create_subject(db_session, "هندسه ۱")
    s2 = create_subject(db_session, "جبر ۱")
    s3 = create_subject(db_session, "حساب ۱")

    # Create custom track
    track = create_track(db_session, "المپیاد ریاضی", "دوره پیشرفته", [s1.id, s2.id])
    assert track.id is not None
    assert track.is_default is False
    assert len(track.subjects) == 2

    # Duplicate track name rejection
    with pytest.raises(TrackAlreadyExistsError):
        create_track(db_session, "المپیاد ریاضی")

    # Add subject
    add_subject_to_track(db_session, track.id, s3.id)
    db_session.refresh(track)
    assert len(track.subjects) == 3

    # Remove subject
    remove_subject_from_track(db_session, track.id, s1.id)
    db_session.refresh(track)
    assert len(track.subjects) == 2
    assert s1 not in track.subjects

    # Update track
    updated = update_track(db_session, track.id, "المپیاد ریاضی پیشرفته")
    assert updated.name == "المپیاد ریاضی پیشرفته"

    # Delete track
    delete_track(db_session, track.id)
    assert get_track_by_id(db_session, track.id) is None


def test_student_track_assignment_and_subject_customization(db_session: Session):
    s1 = create_subject(db_session, "درس ۱")
    s2 = create_subject(db_session, "درس ۲")
    s3 = create_subject(db_session, "درس ۳")
    track = create_track(db_session, "رشته آزمایشی", subject_ids=[s1.id, s2.id])

    student = create_student(
        db=db_session,
        full_name="علی رضایی",
        username="alireza",
        password="PassWord123!",
    )

    # 1. Assign track
    assign_student_track(db_session, student.id, track.id)
    db_session.refresh(student)
    assert student.academic_track_id == track.id
    assert student.is_subjects_customized is False

    # Default effective subjects should be track subjects
    effective_subs = get_student_effective_subjects(student)
    assert len(effective_subs) == 2
    assert s1 in effective_subs and s2 in effective_subs

    # 2. Customize student subjects (e.g. they only take درس ۱ and درس ۳)
    customize_student_subjects(db_session, student.id, [s1.id, s3.id])
    db_session.refresh(student)
    assert student.is_subjects_customized is True

    custom_subs = get_student_effective_subjects(student)
    assert len(custom_subs) == 2
    assert s1 in custom_subs and s3 in custom_subs
    assert s2 not in custom_subs

    # 3. Future track modification should NOT affect student's customized subject list
    remove_subject_from_track(db_session, track.id, s1.id)
    db_session.refresh(student)
    after_track_edit_subs = get_student_effective_subjects(student)
    assert s1 in after_track_edit_subs  # Still in customized list!

    # 4. Reset to track defaults
    reset_student_subjects_to_track(db_session, student.id)
    db_session.refresh(student)
    assert student.is_subjects_customized is False
    reset_subs = get_student_effective_subjects(student)
    assert s1 not in reset_subs  # Now mirrors current track!
    assert s2 in reset_subs


def test_subject_in_use_prevents_deletion(db_session: Session):
    s = create_subject(db_session, "فیزیک پایه")
    track = create_track(db_session, "رشته فیزیک", subject_ids=[s.id])

    # Deletion should fail because it is referenced in a track
    with pytest.raises(SubjectInUseError):
        delete_subject(db_session, s.id)

    # After removing from track, subject can be deleted
    remove_subject_from_track(db_session, track.id, s.id)
    delete_subject(db_session, s.id)
    assert get_subject_by_id(db_session, s.id) is None


def test_track_in_use_prevents_deletion(db_session: Session):
    track = create_track(db_session, "رشته تجربی آزمایشی")
    student = create_student(
        db=db_session,
        full_name="مریم سعیدی",
        username="maryam",
        password="PassWord123!",
    )
    assign_student_track(db_session, student.id, track.id)

    # Deleting track should fail because a student is assigned
    with pytest.raises(TrackInUseError):
        delete_track(db_session, track.id)

    # Unassign student, then track can be deleted
    assign_student_track(db_session, student.id, None)
    delete_track(db_session, track.id)
    assert get_track_by_id(db_session, track.id) is None


