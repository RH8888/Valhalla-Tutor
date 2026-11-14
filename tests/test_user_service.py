import pytest
from sqlalchemy.orm import Session
from app.core.security import verify_password
from app.models.user import UserRole
from app.services.auth_service import create_session, get_user_and_session_by_token
from app.services.user_service import (
    UserAlreadyExistsError,
    UserNotFoundError,
    create_student,
    get_student_by_id,
    list_students,
    reset_student_password,
    set_student_active_status,
)


def test_create_student_success(db_session: Session):
    student = create_student(
        db=db_session,
        username="john_doe",
        full_name="John Doe",
        password="MySecretPassword123!",
        email="john@example.com",
    )
    assert student.id is not None
    assert student.username == "john_doe"
    assert student.full_name == "John Doe"
    assert student.email == "john@example.com"
    assert student.role == UserRole.STUDENT
    assert student.is_active is True
    assert student.timezone == "Asia/Tehran"
    assert verify_password("MySecretPassword123!", student.hashed_password)


def test_create_student_duplicate_username(db_session: Session):
    create_student(
        db=db_session,
        username="unique_user",
        full_name="User 1",
        password="pass",
    )
    with pytest.raises(UserAlreadyExistsError, match="already taken"):
        create_student(
            db=db_session,
            username="UNIQUE_USER",
            full_name="User 2",
            password="pass",
        )


def test_create_student_duplicate_email(db_session: Session):
    create_student(
        db=db_session,
        username="user1",
        full_name="User 1",
        password="pass",
        email="common@example.com",
    )
    with pytest.raises(UserAlreadyExistsError, match="already in use"):
        create_student(
            db=db_session,
            username="user2",
            full_name="User 2",
            password="pass",
            email="common@example.com",
        )


def test_list_students(db_session: Session):
    s1 = create_student(db=db_session, username="bob", full_name="Bob", password="p")
    s2 = create_student(db=db_session, username="alice", full_name="Alice", password="p")
    set_student_active_status(db=db_session, student_id=s1.id, is_active=False)

    all_students = list_students(db=db_session, include_inactive=True)
    assert len(all_students) == 2
    # Ordered by full name: Alice, Bob
    assert all_students[0].username == "alice"
    assert all_students[1].username == "bob"

    active_only = list_students(db=db_session, include_inactive=False)
    assert len(active_only) == 1
    assert active_only[0].username == "alice"


def test_reset_password_revokes_sessions(db_session: Session):
    student = create_student(db=db_session, username="sam", full_name="Sam", password="OldPass123!")
    token, session_rec = create_session(db_session, student)

    # Verify session is initially valid
    u, s = get_user_and_session_by_token(db_session, token)
    assert u is not None and s is not None

    # Reset password
    reset_student_password(db_session, student.id, "NewPass456!")
    assert verify_password("NewPass456!", student.hashed_password)
    assert not verify_password("OldPass123!", student.hashed_password)

    # Previous session must be revoked
    u2, s2 = get_user_and_session_by_token(db_session, token)
    assert u2 is None and s2 is None


def test_deactivate_student_revokes_sessions(db_session: Session):
    student = create_student(db=db_session, username="dave", full_name="Dave", password="Pass123!")
    token, session_rec = create_session(db_session, student)

    set_student_active_status(db_session, student.id, is_active=False)
    assert student.is_active is False

    # Session lookup fails for deactivated account
    u, s = get_user_and_session_by_token(db_session, token)
    assert u is None and s is None

