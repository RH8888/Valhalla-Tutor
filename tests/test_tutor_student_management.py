import uuid
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.dependencies import SESSION_COOKIE_NAME
from app.core.security import verify_password
from app.models.user import User, UserRole
from app.services.auth_service import create_session, get_user_and_session_by_token
from app.services.user_service import create_student, get_student_by_id


def test_tutor_student_management_flow(client: TestClient, db_session: Session, tutor_session):
    raw_token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    # 1. Access student listing
    list_resp = client.get("/tutor/students")
    assert list_resp.status_code == 200
    assert "Student Directory" in list_resp.text

    # 2. Access creation page
    create_page_resp = client.get("/tutor/students/create")
    assert create_page_resp.status_code == 200
    assert "Add New Student" in create_page_resp.text

    # 3. Create student
    create_resp = client.post(
        "/tutor/students",
        data={
            "full_name": "Babak Khorramdin",
            "username": "babak",
            "email": "babak@valhalla.local",
            "password": "InitialPass123!",
            "timezone": "Asia/Tehran",
            "csrf_token": session_rec.csrf_token,
        },
        follow_redirects=True,
    )
    assert create_resp.status_code == 200
    assert "Babak Khorramdin" in create_resp.text
    assert "@babak" in create_resp.text

    # Verify student exists in DB
    student = db_session.query(User).filter(User.username == "babak").first()
    assert student is not None
    assert student.role == UserRole.STUDENT
    assert verify_password("InitialPass123!", student.hashed_password)


def test_duplicate_username_rejected_in_ui(client: TestClient, tutor_session):
    raw_token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    # First creation
    client.post(
        "/tutor/students",
        data={
            "full_name": "Student A",
            "username": "dupuser",
            "password": "pass",
            "csrf_token": session_rec.csrf_token,
        },
    )

    # Duplicate creation
    dup_resp = client.post(
        "/tutor/students",
        data={
            "full_name": "Student B",
            "username": "dupuser",
            "password": "pass",
            "csrf_token": session_rec.csrf_token,
        },
    )
    assert dup_resp.status_code == 400
    assert "already taken" in dup_resp.text


def test_tutor_can_reset_student_password(client: TestClient, db_session: Session, tutor_session, student_user: User):
    raw_token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    # Create active session for student
    st_token, st_session = create_session(db_session, student_user)

    # Tutor resets student password
    reset_resp = client.post(
        f"/tutor/students/{student_user.id}/reset-password",
        data={"new_password": "BrandNewPassword123!", "csrf_token": session_rec.csrf_token},
        follow_redirects=True,
    )
    assert reset_resp.status_code == 200
    assert "Password reset successfully" in reset_resp.text

    # Student session must now be revoked
    u, s = get_user_and_session_by_token(db_session, st_token)
    assert u is None and s is None

    # Student can login with new password
    login_resp = client.post(
        "/auth/login",
        data={"identifier": student_user.username, "password": "BrandNewPassword123!"},
        follow_redirects=False,
    )
    assert login_resp.status_code == 303


def test_tutor_can_deactivate_and_activate_student(client: TestClient, db_session: Session, tutor_session, student_user: User):
    raw_token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    # Active session for student
    st_token, _ = create_session(db_session, student_user)

    # Deactivate student
    toggle_resp = client.post(
        f"/tutor/students/{student_user.id}/toggle-status",
        data={"csrf_token": session_rec.csrf_token},
        follow_redirects=True,
    )
    assert toggle_resp.status_code == 200
    assert "deactivated" in toggle_resp.text
    assert "Inactive" in toggle_resp.text

    # Verify session is revoked
    u, s = get_user_and_session_by_token(db_session, st_token)
    assert u is None and s is None

    # Re-activate student
    toggle_resp2 = client.post(
        f"/tutor/students/{student_user.id}/toggle-status",
        data={"csrf_token": session_rec.csrf_token},
        follow_redirects=True,
    )
    assert toggle_resp2.status_code == 200
    assert "activated" in toggle_resp2.text
    assert "Active" in toggle_resp2.text


def test_tutor_access_nonexistent_student(client: TestClient, tutor_session):
    raw_token, _ = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    fake_id = uuid.uuid4()
    resp = client.get(f"/tutor/students/{fake_id}")
    assert resp.status_code == 404


def test_no_public_student_registration(client: TestClient):
    # Verify public registration endpoints do not exist
    for path in ["/register", "/auth/register", "/signup", "/auth/signup"]:
        resp = client.get(path)
        assert resp.status_code in (404, 405)
        post_resp = client.post(path, data={"username": "hacker"})
        assert post_resp.status_code in (404, 405)

