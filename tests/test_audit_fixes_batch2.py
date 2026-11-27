import shutil
import uuid
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.models.practice_exam import PracticeExam, PracticeExamBooklet
from app.routers.tutor_plans import get_student_plans_page, post_delete_plan
from app.routers.tutor_practice_exams import get_practice_attempt_results, get_practice_exam_detail
from app.services.academic_service import (
    TrackInUseError,
    assign_student_track,
    create_subject,
    create_track,
    delete_track,
    set_track_subjects,
)
from app.services.exam_service import create_exam, create_exam_session
from app.services.plan_service import create_study_plan, publish_study_plan
from app.services.practice_exam_service import start_practice_attempt
from app.services.telegram_backup_service import (
    create_and_deliver_manual_backup,
    get_or_create_telegram_settings,
    update_telegram_settings,
)
from app.services.user_service import create_student


def _dummy_request(path: str = "/") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": [],
        "scheme": "http",
        "server": ("testserver", 80),
    }
    return Request(scope)


def test_practice_exam_in_progress_results_guard(
    db_session: Session,
    tutor_user,
    tutor_session,
):
    track = create_track(db_session, name="تجربی آزمونک")
    st = create_student(
        db_session,
        username="st_pe_guard",
        full_name="Practice Student",
        password="Password123!",
        grade="12",
    )
    assign_student_track(db_session, st.id, track.id)

    exam = PracticeExam(
        title="آزمون تستی تستی",
        grade="12",
        academic_track_id=track.id,
        is_timed=False,
        is_active=True,
    )
    db_session.add(exam)
    db_session.flush()
    booklet = PracticeExamBooklet(
        practice_exam_id=exam.id,
        title="دفترچه ۱",
        order_index=1,
        question_start=1,
        question_end=10,
        pdf_file_path="practice_booklets/dummy.pdf",
        pdf_file_name="dummy.pdf",
    )
    db_session.add(booklet)
    db_session.commit()

    attempt = start_practice_attempt(db_session, st, exam.id)
    assert attempt.status == "IN_PROGRESS"

    _, tutor_sess = tutor_session
    detail_resp = get_practice_exam_detail(
        request=_dummy_request(f"/tutor/practice-exams/{exam.id}"),
        exam_id=exam.id,
        db=db_session,
        current_user=tutor_user,
        current_session=tutor_sess,
    )
    assert detail_resp.status_code == 200
    body = detail_resp.body.decode("utf-8")
    assert f"/tutor/practice-exams/attempts/{attempt.id}" not in body
    assert "In Progress" in body

    with pytest.raises(HTTPException) as in_prog_exc:
        get_practice_attempt_results(
            request=_dummy_request(f"/tutor/practice-exams/attempts/{attempt.id}"),
            attempt_id=attempt.id,
            db=db_session,
            current_user=tutor_user,
            current_session=tutor_sess,
        )
    assert in_prog_exc.value.status_code == 400

    with pytest.raises(HTTPException) as missing_exc:
        get_practice_attempt_results(
            request=_dummy_request("/tutor/practice-exams/attempts/missing"),
            attempt_id=uuid.uuid4(),
            db=db_session,
            current_user=tutor_user,
            current_session=tutor_sess,
        )
    assert missing_exc.value.status_code == 404


def test_delete_track_blocks_practice_exam_and_external_exam_references(db_session: Session):
    sub = create_subject(db_session, name="زیست ردیابی", grades=["12"])
    track_pe = create_track(db_session, name="رشته با آزمون تمرینی")
    db_session.add(
        PracticeExam(
            title="آزمون تمرینی وابسته",
            grade="12",
            academic_track_id=track_pe.id,
            is_timed=True,
            is_active=True,
        )
    )
    db_session.commit()

    with pytest.raises(TrackInUseError, match="practice exam"):
        delete_track(db_session, track_pe.id)

    track_ext = create_track(db_session, name="رشته با آزمون خارجی")
    set_track_subjects(db_session, track_ext.id, [sub.id])
    exam = create_exam(db_session, title="آزمون خارجی وابسته")
    create_exam_session(
        db_session,
        exam_id=exam.id,
        exam_date=date(2026, 6, 1),
        track_subjects_map={track_ext.id: [sub.id]},
    )

    with pytest.raises(TrackInUseError, match="external exam"):
        delete_track(db_session, track_ext.id)

    unused = create_track(db_session, name="رشته بدون استفاده")
    delete_track(db_session, unused.id)


def test_post_delete_plan_handles_validation_errors_cleanly(
    db_session: Session,
    tutor_user,
    tutor_session,
):
    st = create_student(
        db_session,
        username="st_plan_del",
        full_name="Plan Delete Student",
        password="Password123!",
        grade="12",
    )
    plan = create_study_plan(
        db_session,
        tutor_id=tutor_user.id,
        student_id=st.id,
        start_date=date(2026, 6, 1),
        title="Published Plan",
    )
    publish_study_plan(db_session, plan.id, tutor_id=tutor_user.id)

    resp = post_delete_plan(
        plan_id=plan.id,
        db=db_session,
        current_user=tutor_user,
    )
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith(f"/tutor/students/{st.id}/plans?err=")

    _, tutor_sess = tutor_session
    page_resp = get_student_plans_page(
        student_id=st.id,
        request=_dummy_request(f"/tutor/students/{st.id}/plans"),
        err="Cannot delete a published study plan.",
        db=db_session,
        current_user=tutor_user,
        current_session=tutor_sess,
    )
    assert page_resp.status_code == 200
    assert "Cannot delete a published study plan." in page_resp.body.decode("utf-8")


def test_dockerfile_installs_pg16_client_and_missing_pg_dump_fails_clearly_for_postgres(
    db_session: Session,
    tmp_path: Path,
    monkeypatch,
):
    dockerfile_text = Path("Dockerfile").read_text(encoding="utf-8")
    assert "postgresql-client-16" in dockerfile_text

    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path / "uploads"))
    (tmp_path / "uploads").mkdir(parents=True, exist_ok=True)
    update_telegram_settings(
        db_session,
        enabled=True,
        chat_id="123456",
        new_bot_token="999888777:AA_PGDump_Guard_Token",
    )

    monkeypatch.setattr(
        type(create_and_deliver_manual_backup.__globals__["settings"]),
        "sync_database_url",
        property(lambda self: "postgresql+psycopg2://postgres:postgres@db:5432/valhalla_db"),
    )
    monkeypatch.setattr(db_session.bind.dialect, "name", "postgresql")
    monkeypatch.setattr(shutil, "which", lambda cmd: None)

    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True}))
    with httpx.Client(transport=transport) as client:
        res = create_and_deliver_manual_backup(db_session, client=client)

    assert res.delivered is False
    assert "pg_dump" in res.message
    rec = get_or_create_telegram_settings(db_session)
    assert rec.last_backup_success is False
    assert "pg_dump" in (rec.last_backup_message or "")
