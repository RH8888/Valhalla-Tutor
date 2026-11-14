from fastapi.testclient import TestClient
from app.core.dependencies import SESSION_COOKIE_NAME


def test_csrf_get_safe_method_allowed(client: TestClient, tutor_session):
    raw_token, _ = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    response = client.get("/tutor/students")
    assert response.status_code == 200


def test_csrf_post_without_token_rejected(client: TestClient, tutor_session):
    raw_token, _ = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    response = client.post(
        "/tutor/students",
        data={"full_name": "Test", "username": "test_student", "password": "pass"},
    )
    assert response.status_code == 403
    assert "Invalid or missing CSRF token" in response.json()["detail"]


def test_csrf_post_with_invalid_token_rejected(client: TestClient, tutor_session):
    raw_token, _ = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    response = client.post(
        "/tutor/students",
        data={"full_name": "Test", "username": "test_student", "password": "pass"},
        headers={"X-CSRF-Token": "invalid-token-string"},
    )
    assert response.status_code == 403
    assert "Invalid or missing CSRF token" in response.json()["detail"]


def test_csrf_post_with_valid_header_token_accepted(client: TestClient, tutor_session):
    raw_token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    response = client.post(
        "/tutor/students",
        data={"full_name": "New Student", "username": "new_student", "password": "pass"},
        headers={"X-CSRF-Token": session_rec.csrf_token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "/tutor/students/" in response.headers["location"]


def test_csrf_post_with_valid_form_field_token_accepted(client: TestClient, tutor_session):
    raw_token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    response = client.post(
        "/tutor/students",
        data={
            "full_name": "Another Student",
            "username": "another_student",
            "password": "pass",
            "csrf_token": session_rec.csrf_token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "/tutor/students/" in response.headers["location"]

