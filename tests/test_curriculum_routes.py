import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.dependencies import SESSION_COOKIE_NAME
from app.models.user import User
from app.services.academic_service import (
    create_subject,
    create_track,
    seed_default_academic_data,
)
from app.services.user_service import create_student


def test_tutor_curriculum_routes_flow(client: TestClient, db_session: Session, tutor_session):
    raw_token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    # 1. Subjects list page
    resp = client.get("/tutor/subjects")
    assert resp.status_code == 200
    assert "Academic Subjects" in resp.text

    # 2. Create subject via form
    create_sub_resp = client.post(
        "/tutor/subjects",
        data={
            "name": "فیزیک نهایی",
            "description": "فیزیک دوازدهم نهایی",
            "csrf_token": session_rec.csrf_token,
        },
        follow_redirects=True,
    )
    assert create_sub_resp.status_code == 200
    assert "فیزیک نهایی" in create_sub_resp.text

    # 3. Academic Tracks list page
    resp_tracks = client.get("/tutor/tracks")
    assert resp_tracks.status_code == 200
    assert "Academic Tracks" in resp_tracks.text

    # 4. Videos dashboard
    resp_videos = client.get("/tutor/videos")
    assert resp_videos.status_code == 200
    assert "Video Courses" in resp_videos.text

    # 5. Books dashboard
    resp_books = client.get("/tutor/books")
    assert resp_books.status_code == 200
    assert "Test Books" in resp_books.text


def test_student_read_only_curriculum_and_tutor_assignment(
    client: TestClient, db_session: Session, tutor_session
):
    seed_default_academic_data(db_session)
    from app.services.academic_service import get_track_by_name
    math_track = get_track_by_name(db_session, "ریاضی")

    student = create_student(
        db=db_session,
        full_name="نگار رحیمی",
        username="negar",
        password="StudentPassword123!",
    )

    raw_token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    # Tutor assigns track to student
    assign_resp = client.post(
        f"/tutor/students/{student.id}/assign-track",
        data={
            "track_id": str(math_track.id),
            "csrf_token": session_rec.csrf_token,
        },
        follow_redirects=True,
    )
    assert assign_resp.status_code == 200
    assert "Academic track updated successfully" in assign_resp.text
    assert "ریاضی" in assign_resp.text

    # Student login to view curriculum
    from app.services.auth_service import create_session
    s_token, _ = create_session(db_session, student)
    client.cookies.set(SESSION_COOKIE_NAME, s_token)

    curriculum_resp = client.get("/student/curriculum")
    assert curriculum_resp.status_code == 200
    assert "My Academic Curriculum" in curriculum_resp.text
    assert "ریاضی" in curriculum_resp.text
    assert "حسابان" in curriculum_resp.text
    assert "Standard Track Curriculum" in curriculum_resp.text

    # Student cannot access tutor routes (403 Forbidden)
    forbidden_resp = client.get("/tutor/tracks")
    assert forbidden_resp.status_code == 403

