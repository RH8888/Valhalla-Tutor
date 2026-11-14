from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.dependencies import SESSION_COOKIE_NAME
from app.models.session import UserSession
from app.models.user import User


def test_get_login_page(client: TestClient):
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert "Sign In" in response.text


def test_login_success_username(client: TestClient, tutor_user: User):
    response = client.post(
        "/auth/login",
        data={"identifier": "headtutor", "password": "TutorSecretPassword123!"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/tutor/students"
    assert SESSION_COOKIE_NAME in response.cookies
    # Verify cookie attributes
    cookie_header = response.headers.get("set-cookie", "")
    assert "httponly" in cookie_header.lower()
    assert "samesite=lax" in cookie_header.lower()


def test_login_success_email(client: TestClient, tutor_user: User):
    response = client.post(
        "/auth/login",
        data={"identifier": "tutor@valhalla.local", "password": "TutorSecretPassword123!"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/tutor/students"
    assert SESSION_COOKIE_NAME in response.cookies


def test_login_invalid_password(client: TestClient, tutor_user: User):
    response = client.post(
        "/auth/login",
        data={"identifier": "headtutor", "password": "WrongPassword!"},
    )
    assert response.status_code == 401
    assert "Invalid username/email or password" in response.text
    assert SESSION_COOKIE_NAME not in response.cookies


def test_login_rate_limiting(client: TestClient, tutor_user: User):
    # Perform 5 failed attempts
    for _ in range(5):
        resp = client.post(
            "/auth/login",
            data={"identifier": "headtutor", "password": "WrongPassword!"},
        )
        assert resp.status_code == 401

    # 6th attempt should be blocked by rate limiter with 429
    blocked_resp = client.post(
        "/auth/login",
        data={"identifier": "headtutor", "password": "WrongPassword!"},
    )
    assert blocked_resp.status_code == 429
    assert "Too many failed login attempts" in blocked_resp.text


def test_logout(client: TestClient, db_session: Session, tutor_session):
    raw_token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    response = client.post(
        "/auth/logout",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"

    # Verify session is revoked in database
    db_session.refresh(session_rec)
    assert session_rec.is_revoked is True

