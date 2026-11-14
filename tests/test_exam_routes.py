import uuid
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.dependencies import SESSION_COOKIE_NAME
from app.models.track import AcademicTrack
from app.models.user import User
from app.services.academic_service import assign_student_track, create_subject, create_track, set_track_subjects
from app.services.exam_service import create_exam, create_exam_session
from app.services.user_service import create_student


def test_tutor_exams_endpoints(client: TestClient, db_session: Session, tutor_session):
    raw_token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    # 1. Access listing
    res = client.get("/tutor/exams")
    assert res.status_code == 200
    assert "Exam Management" in res.text

    # 2. Access creation page
    res = client.get("/tutor/exams/create")
    assert res.status_code == 200

    # 3. Create exam
    res = client.post(
        "/tutor/exams/create",
        data={
            "title": "آزمون آزمایشی سنجش",
            "description": "دوره اول",
            "csrf_token": session_rec.csrf_token,
        },
        follow_redirects=False,
    )
    assert res.status_code == 303

    # 4. Schedule session page
    res = client.get("/tutor/exams/sessions/create")
    assert res.status_code == 200

    # Setup track & subjects for scheduling
    sub1 = create_subject(db_session, name="ادبیات عمومی", grades=["10", "11", "12"])
    track1 = create_track(db_session, name="عمومی آزمون")
    set_track_subjects(db_session, track1.id, [sub1.id])

    exam = create_exam(db_session, title="آزمون سنجش ۱")

    # 5. Schedule session
    form_data = {
        "exam_id": str(exam.id),
        "date": "2026-11-20",
        "title": "نوبت پاییز",
        "track_ids": [str(track1.id)],
        f"track_{track1.id}_subjects": [str(sub1.id)],
        "csrf_token": session_rec.csrf_token,
    }
    res = client.post("/tutor/exams/sessions/create", data=form_data, follow_redirects=False)
    assert res.status_code == 303
    session_url = res.headers["location"]

    # 6. View session detail
    res = client.get(session_url)
    assert res.status_code == 200
    assert "آزمون سنجش ۱" in res.text


def test_student_exam_workflow_and_analytics(client: TestClient, db_session: Session, student_user: User, student_session):
    raw_token, session_rec = student_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    # Setup curriculum
    sub_math = create_subject(db_session, name="ریاضی جامع", grades=["10", "11", "12"])
    track_math = create_track(db_session, name="ریاضی فیزیک ۱")
    set_track_subjects(db_session, track_math.id, [sub_math.id])
    assign_student_track(db_session, student_user.id, track_math.id)

    exam = create_exam(db_session, title="آزمون ریاضی جامع")
    session = create_exam_session(
        db_session,
        exam_id=exam.id,
        exam_date=date(2026, 11, 15),
        track_subjects_map={track_math.id: [sub_math.id]},
    )

    # 1. Student exam listing
    res = client.get("/student/exams")
    assert res.status_code == 200
    assert "آزمون ریاضی جامع" in res.text

    # 2. Get submission form
    res = client.get(f"/student/exams/{session.id}/submit")
    assert res.status_code == 200
    assert "ریاضی جامع" in res.text

    # 3. Submit results
    res = client.post(
        f"/student/exams/{session.id}/submit",
        data={
            f"correct_{sub_math.id}": "25",
            f"incorrect_{sub_math.id}": "5",
            f"percentage_{sub_math.id}": "76.5",
            "overall_rank": "42",
            "notes": "آزمون خوبی بود",
            "csrf_token": session_rec.csrf_token,
        },
        follow_redirects=False,
    )
    assert res.status_code == 303

    # 4. View student analytics page
    res = client.get("/student/exams/analytics")
    assert res.status_code == 200
    assert "Exam Performance Analytics" in res.text
    assert "76.5%" in res.text


def test_exam_routes_authorization_boundaries(client: TestClient, student_session, tutor_session):
    student_token, _ = student_session
    tutor_token, _ = tutor_session

    # Student cannot access tutor exams
    client.cookies.set(SESSION_COOKIE_NAME, student_token)
    res = client.get("/tutor/exams")
    assert res.status_code == 403

    # Tutor cannot access student exams
    client.cookies.set(SESSION_COOKIE_NAME, tutor_token)
    res = client.get("/student/exams")
    assert res.status_code == 403
