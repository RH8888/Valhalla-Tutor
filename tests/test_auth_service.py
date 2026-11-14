from datetime import timedelta
import pytest
from sqlalchemy.orm import Session
from app.core.timezone import now_utc
from app.services.auth_service import (
    authenticate_user,
    create_session,
    get_user_and_session_by_token,
    revoke_all_user_sessions,
    revoke_session,
)
from app.services.user_service import create_student, set_student_active_status


def test_authenticate_user_success(db_session: Session):
    student = create_student(
        db=db_session,
        username="learner",
        full_name="Learner One",
        password="PassWord123!",
        email="learner@valhalla.local",
    )
    # Auth by username
    u1 = authenticate_user(db_session, "learner", "PassWord123!")
    assert u1 is not None
    assert u1.id == student.id

    # Auth by email
    u2 = authenticate_user(db_session, "learner@valhalla.local", "PassWord123!")
    assert u2 is not None
    assert u2.id == student.id


def test_authenticate_user_failures(db_session: Session):
    student = create_student(
        db=db_session,
        username="learner2",
        full_name="Learner Two",
        password="PassWord123!",
    )
    # Wrong password
    assert authenticate_user(db_session, "learner2", "WrongPassword") is None
    # Unknown user
    assert authenticate_user(db_session, "nonexistent", "PassWord123!") is None
    # Inactive user
    set_student_active_status(db_session, student.id, is_active=False)
    assert authenticate_user(db_session, "learner2", "PassWord123!") is None


def test_session_lifecycle(db_session: Session):
    student = create_student(
        db=db_session,
        username="session_user",
        full_name="Session User",
        password="PassWord123!",
    )
    raw_token, session_rec = create_session(db_session, student)
    assert raw_token != session_rec.token_hash
    assert len(session_rec.csrf_token) >= 32

    # Lookup valid session
    u, s = get_user_and_session_by_token(db_session, raw_token)
    assert u is not None and s is not None
    assert u.id == student.id

    # Revoke session
    assert revoke_session(db_session, raw_token) is True
    u_revoked, s_revoked = get_user_and_session_by_token(db_session, raw_token)
    assert u_revoked is None and s_revoked is None


def test_session_expiration(db_session: Session):
    student = create_student(
        db=db_session,
        username="exp_user",
        full_name="Exp User",
        password="PassWord123!",
    )
    raw_token, session_rec = create_session(db_session, student)

    # Artificially expire the session
    session_rec.expires_at = now_utc() - timedelta(minutes=1)
    db_session.commit()

    u, s = get_user_and_session_by_token(db_session, raw_token)
    assert u is None and s is None

