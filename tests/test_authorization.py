from datetime import timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.dependencies import SESSION_COOKIE_NAME
from app.core.timezone import now_utc
from app.models.user import User


def test_unauthenticated_tutor_access_rejected(client: TestClient):
    response = client.get("/tutor/students")
    assert response.status_code == 401
    assert "Not authenticated" in response.json()["detail"]


def test_student_cannot_access_tutor_routes(client: TestClient, student_session):
    raw_token, _ = student_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    response = client.get("/tutor/students")
    assert response.status_code == 403
    assert "Tutor privileges required" in response.json()["detail"]


def test_tutor_can_access_tutor_routes(client: TestClient, tutor_session):
    raw_token, _ = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    response = client.get("/tutor/students")
    assert response.status_code == 200
    assert "Student Directory" in response.text


def test_student_can_access_student_routes(client: TestClient, student_session, student_user: User):
    raw_token, _ = student_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    response = client.get("/student/profile")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(student_user.id)
    assert data["username"] == student_user.username
    assert data["role"] == "STUDENT"


def test_tutor_cannot_access_student_only_routes(client: TestClient, tutor_session):
    raw_token, _ = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    response = client.get("/student/profile")
    assert response.status_code == 403
    assert "Student privileges required" in response.json()["detail"]


def test_expired_session_rejected(client: TestClient, db_session: Session, tutor_session):
    raw_token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    # Expire the session
    session_rec.expires_at = now_utc() - timedelta(minutes=5)
    db_session.commit()

    response = client.get("/tutor/students")
    assert response.status_code == 401
    assert "Inactive or invalid session" in response.json()["detail"]


def test_revoked_session_rejected(client: TestClient, db_session: Session, tutor_session):
    raw_token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    session_rec.is_revoked = True
    db_session.commit()

    response = client.get("/tutor/students")
    assert response.status_code == 401
    assert "Inactive or invalid session" in response.json()["detail"]

