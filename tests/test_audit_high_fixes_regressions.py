import asyncio
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.orm import Session
from starlette.datastructures import FormData
from starlette.requests import Request

from app.core.config import Settings
from app.main import app, lifespan
from app.models.exam import Exam, ExamAuditLog, ExamSession
from app.models.practice_exam import PracticeExamAssignment, PracticeExamBooklet, StudentPracticeAttempt
from app.models.user import User
from app.routers.tutor_exams import post_configure_grade_track
from app.services.academic_service import (
    assign_student_track,
    create_subject,
    create_track,
    set_track_subjects,
)
from app.services.exam_service import (
    assign_exam_series_to_students,
    bulk_assign_occurrences_to_students,
    compare_students_on_session,
    create_exam,
    create_exam_session,
    delete_exam_session,
    get_all_series_incompatible_students,
    get_exam_by_id,
    get_exam_series_analytics,
    get_student_available_exams,
    get_student_comprehensive_analytics,
    list_exam_audit_logs,
    safe_delete_exam_series,
    submit_student_exam_result,
)
from app.services.message_service import (
    get_or_create_conversation,
    list_tutor_conversations,
    send_message,
)
from app.services.practice_exam_service import (
    create_practice_exam,
    get_student_available_practice_exams,
)
from app.services.telegram_backup_service import (
    run_scheduled_backup_tick,
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


def test_high01_configure_grade_track_blank_group_resolves_subject_name(
    db_session: Session,
    tutor_user: User,
    tutor_session,
):
    sub_bio = create_subject(db_session, name="زیست‌شناسی", grades=["11"])
    sub_chem = create_subject(db_session, name="شیمی", grades=["11"])
    track = create_track(db_session, name="تجربی پایه")
    set_track_subjects(db_session, track.id, [sub_bio.id, sub_chem.id])

    exam = create_exam(db_session, title="Series Blank Group Test")
    _, tutor_sess = tutor_session

    form = FormData(
        [
            ("grade", "11"),
            ("track_id", str(track.id)),
            ("selected_subjects", str(sub_bio.id)),
            (f"subject_group_{sub_bio.id}", "زیست تخصصی"),
            ("selected_subjects", str(sub_chem.id)),
            (f"subject_group_{sub_chem.id}", ""),
        ]
    )
    response = post_configure_grade_track(
        request=_dummy_request(f"/tutor/exams/{exam.id}/grade-tracks/create"),
        exam_id=exam.id,
        form_data=form,
        db=db_session,
        current_user=tutor_user,
        current_session=tutor_sess,
    )
    assert response.status_code == 303

    reloaded = get_exam_by_id(db_session, exam.id, populate_existing=True)
    assert reloaded is not None
    assert len(reloaded.grade_track_configs) == 1
    titles = {rg.title for rg in reloaded.grade_track_configs[0].reporting_groups}
    assert titles == {"زیست تخصصی", "شیمی"}


def test_high03_scheduled_backup_acquires_lock_before_next_run_and_rolls_back(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path / "uploads"))
    (tmp_path / "uploads").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(db_session.bind.dialect, "name", "postgresql")

    rec = update_telegram_settings(
        db_session,
        enabled=True,
        chat_id="123456",
        new_bot_token="999888777:AA_LockOrder_Token",
        schedule_enabled=True,
        schedule_mode="interval",
        interval_value=4,
        interval_unit="hours",
    )
    rec.next_run_at = datetime(2020, 1, 1, 0, 0, tzinfo=timezone.utc)
    db_session.commit()

    events = []
    real_execute = db_session.execute
    real_rollback = db_session.rollback
    real_commit = db_session.commit

    class _ScalarResult:
        def __init__(self, val):
            self._val = val

        def scalar(self):
            return self._val

    def spy_execute(stmt, *args, **kwargs):
        sql = str(stmt)
        if "pg_try_advisory_lock" in sql:
            events.append("lock_try")
            return _ScalarResult(False)
        if "pg_advisory_unlock" in sql:
            events.append("unlock")
            return _ScalarResult(True)
        events.append("other_execute")
        return real_execute(stmt, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", spy_execute)
    assert run_scheduled_backup_tick(db_session) is False
    # Lock contention returns before reading/updating settings
    assert events == ["lock_try"]

    events.clear()

    def spy_execute_acquired(stmt, *args, **kwargs):
        sql = str(stmt)
        if "pg_try_advisory_lock" in sql:
            events.append("lock_try")
            return _ScalarResult(True)
        if "pg_advisory_unlock" in sql:
            events.append("unlock")
            return _ScalarResult(True)
        events.append(f"sql:{sql[:40]}")
        return real_execute(stmt, *args, **kwargs)

    def spy_rollback():
        events.append("rollback")
        return real_rollback()

    def spy_commit():
        events.append("commit")
        return real_commit()

    monkeypatch.setattr(db_session, "execute", spy_execute_acquired)
    monkeypatch.setattr(db_session, "rollback", spy_rollback)
    monkeypatch.setattr(db_session, "commit", spy_commit)

    with (
        patch(
            "app.services.telegram_backup_service.create_and_deliver_manual_backup",
            side_effect=RuntimeError("db failure"),
        ),
        patch("app.services.telegram_backup_service._record_status") as mock_record_status,
    ):
        mock_record_status.side_effect = lambda *_a, **_kw: events.append("record_status")
        ran = run_scheduled_backup_tick(db_session)

    assert ran is True
    assert events[0] == "lock_try"
    rec_idx = events.index("record_status")
    unlock_idx = events.index("unlock")
    assert "rollback" in events[:rec_idx]
    assert "rollback" in events[rec_idx:unlock_idx]


def test_high04_subject_results_fallback_and_grade_filter_normalization(
    db_session: Session,
    tutor_user: User,
):
    sub_phys = create_subject(db_session, name="فیزیک", grades=["11", "10"])
    sub_chem = create_subject(db_session, name="شیمی پایه", grades=["11", "10"])
    track = create_track(db_session, name="تجربی")
    set_track_subjects(db_session, track.id, [sub_phys.id, sub_chem.id])

    st11 = create_student(
        db_session,
        username="st11_ui",
        password="Password123!",
        full_name="Student Grade 11",
        grade="11",
    )
    st10 = create_student(
        db_session,
        username="st10_ui",
        password="Password123!",
        full_name="Student Grade 10",
        grade="10",
    )
    assign_student_track(db_session, st11.id, track.id)
    assign_student_track(db_session, st10.id, track.id)

    exam = create_exam(db_session, title="Subject-Only Exam Series")
    s1 = create_exam_session(
        db_session,
        exam_id=exam.id,
        exam_date=date.today() - timedelta(days=7),
        track_subjects_map={track.id: [sub_phys.id, sub_chem.id]},
    )
    s2 = create_exam_session(
        db_session,
        exam_id=exam.id,
        exam_date=date.today() - timedelta(days=1),
        track_subjects_map={track.id: [sub_phys.id, sub_chem.id]},
    )
    bulk_assign_occurrences_to_students(db_session, [s1.id, s2.id], [st11.id, st10.id], actor_id=tutor_user.id)

    submit_student_exam_result(
        db_session,
        exam_session_id=s1.id,
        student_id=st11.id,
        subject_data=[
            {"subject_id": sub_phys.id, "correct_answers": 16, "incorrect_answers": 4, "percentage": 80.0},
            {"subject_id": sub_chem.id, "correct_answers": 18, "incorrect_answers": 2, "percentage": 90.0},
        ],
        overall_rank=50,
    )
    submit_student_exam_result(
        db_session,
        exam_session_id=s2.id,
        student_id=st11.id,
        subject_data=[
            {"subject_id": sub_phys.id, "correct_answers": 14, "incorrect_answers": 6, "percentage": 60.0},
            {"subject_id": sub_chem.id, "correct_answers": 16, "incorrect_answers": 4, "percentage": 70.0},
        ],
        overall_rank=70,
    )

    # Persian UI grade string matches UI-stored "11" and normalizes filter_grade to "11"
    comp_fa = compare_students_on_session(db_session, session_id=s1.id, grade="یازدهم")
    comp_num = compare_students_on_session(db_session, session_id=s1.id, grade="11")
    assert comp_fa["filter_grade"] == "11"
    assert comp_fa["total_assigned"] == 1
    assert comp_fa["submitted_count"] == 1
    assert comp_fa["group_averages"] == {"فیزیک": 80.0, "شیمی پایه": 90.0}
    assert comp_fa["rows"][0]["average_percentage"] == 85.0
    assert comp_num["rows"] == comp_fa["rows"]

    series_analytics = get_exam_series_analytics(db_session, exam.id)
    assert series_analytics["reporting_group_averages"] == {"فیزیک": 70.0, "شیمی پایه": 80.0}
    assert series_analytics["consecutive_comparisons"][0]["average_percentage"] == 85.0
    assert series_analytics["consecutive_comparisons"][1]["average_percentage"] == 65.0

    comp_analytics = get_student_comprehensive_analytics(db_session, st11.id, exam_id=exam.id)
    assert comp_analytics["overall_average"] == 75.0
    assert comp_analytics["group_stats"]["فیزیک"]["average"] == 70.0
    assert comp_analytics["group_stats"]["شیمی پایه"]["latest"] == 70.0
    assert comp_analytics["consecutive_comparisons"][1]["change_from_previous"] == -20.0

    compare_html = Path("app/templates/tutor/exams/compare_students.html").read_text(encoding="utf-8")
    assert '<option value="10"' in compare_html
    assert '<option value="11"' in compare_html
    assert '<option value="12"' in compare_html
    assert '<option value="دهم"' not in compare_html


def test_high05_exam_audit_logs_preserved_on_series_delete_and_migration(
    db_session: Session,
    tutor_user: User,
    tmp_path: Path,
):
    exam = create_exam(db_session, title="Audited Deletable Series", description="Temp")
    sess = create_exam_session(
        db_session,
        exam_id=exam.id,
        exam_date=date.today() + timedelta(days=5),
    )

    with (
        patch("app.services.exam_service._lock_session_row", return_value=sess.id) as lock_sess,
        patch("app.services.exam_service._lock_exam_row", return_value=exam.id) as lock_exam,
    ):
        delete_exam_session(db_session, sess.id, actor_id=tutor_user.id)
        safe_delete_exam_series(db_session, exam.id, actor_id=tutor_user.id)
        assert lock_sess.called
        assert lock_exam.called

    assert get_exam_by_id(db_session, exam.id) is None
    series_logs = list_exam_audit_logs(db_session, entity_type="SERIES", entity_id=exam.id)
    actions = {log.action for log in series_logs}
    assert {"CREATED", "DELETED"}.issubset(actions)
    for log in series_logs:
        assert log.exam_id is None
    deleted_log = next(log for log in series_logs if log.action == "DELETED")
    assert json.loads(deleted_log.previous_value or "{}")["title"] == "Audited Deletable Series"

    # Verify Alembic head (5f6a7b8c9d0e) + ON DELETE SET NULL + downgrade -> upgrade cycle
    db_file = tmp_path / "alembic_audit.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_file}")
    command.upgrade(cfg, "head")
    eng = sa.create_engine(f"sqlite:///{db_file}")
    try:
        insp = sa.inspect(eng)
        fk = next(f for f in insp.get_foreign_keys("exam_audit_logs") if f["constrained_columns"] == ["exam_id"])
        assert fk["options"].get("ondelete") == "SET NULL"

        with eng.begin() as conn:
            conn.execute(sa.text("PRAGMA foreign_keys=ON"))
            ex_id = uuid.uuid4().hex
            aud_id = uuid.uuid4().hex
            ent_id = uuid.uuid4().hex
            conn.execute(
                sa.text(
                    "INSERT INTO exams (id, title, is_active, is_archived, created_at, updated_at) "
                    "VALUES (:id, 'Test FK', 1, 0, '2026-11-27 00:00:00', '2026-11-27 00:00:00')"
                ),
                {"id": ex_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO exam_audit_logs (id, entity_type, entity_id, exam_id, action, created_at) "
                    "VALUES (:id, 'SERIES', :ent_id, :exam_id, 'DELETED', '2026-11-27 00:00:00')"
                ),
                {"id": aud_id, "ent_id": ent_id, "exam_id": ex_id},
            )
            conn.execute(sa.text("DELETE FROM exams WHERE id = :id"), {"id": ex_id})
            row = conn.execute(
                sa.text("SELECT exam_id, action FROM exam_audit_logs WHERE id = :id"),
                {"id": aud_id},
            ).fetchone()
            assert row is not None
            assert row[0] is None and row[1] == "DELETED"

        command.downgrade(cfg, "4e5f6a7b8c9d")
        insp_down = sa.inspect(eng)
        fk_down = next(f for f in insp_down.get_foreign_keys("exam_audit_logs") if f["constrained_columns"] == ["exam_id"])
        assert fk_down["options"].get("ondelete") == "CASCADE"

        command.upgrade(cfg, "head")
    finally:
        eng.dispose()


def test_high06_production_startup_validates_secrets(monkeypatch: pytest.MonkeyPatch):
    # Dev & test allow default values
    Settings(ENVIRONMENT="development", _env_file=None).validate_production_settings()
    Settings(ENVIRONMENT="test", _env_file=None).validate_production_settings()

    # Production rejects default SECRET_KEY, short key, placeholder key, and default DB password
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="dev-secret-key-please-change-in-production-min-32-chars",
            POSTGRES_PASSWORD="StrongPassword123!",
            _env_file=None,
        ).validate_production_settings()

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="too-short",
            POSTGRES_PASSWORD="StrongPassword123!",
            _env_file=None,
        ).validate_production_settings()

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="replace_with_strong_random_secret_key_min_32_chars",
            POSTGRES_PASSWORD="StrongPassword123!",
            _env_file=None,
        ).validate_production_settings()

    with pytest.raises(RuntimeError, match="POSTGRES_PASSWORD"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="x" * 64,
            POSTGRES_PASSWORD="postgres",
            _env_file=None,
        ).validate_production_settings()

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="x" * 64,
            DATABASE_URL="postgresql://postgres:postgres@db:5432/valhalla_db",
            _env_file=None,
        ).validate_production_settings()

    # Valid production credentials succeed cleanly
    Settings(
        ENVIRONMENT="production",
        SECRET_KEY="9f4a" * 16,
        POSTGRES_PASSWORD="StrongRandomPassword!2026",
        _env_file=None,
    ).validate_production_settings()

    # FastAPI lifespan fails closed on boot in production with insecure config
    insecure_prod = Settings(
        ENVIRONMENT="production",
        SECRET_KEY="dev-secret-key-please-change-in-production-min-32-chars",
        POSTGRES_PASSWORD="StrongPassword123!",
        _env_file=None,
    )
    monkeypatch.setattr("app.main.settings", insecure_prod)

    async def _run_lifespan():
        async with lifespan(app):
            pass

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        asyncio.run(_run_lifespan())


def test_high08_query_scaling_and_single_unread_poller(
    db_session: Session,
    tutor_user: User,
):
    sub = create_subject(db_session, name="ریاضی", grades=["10", "11", "12"])
    track = create_track(db_session, name="ریاضی فیزیک")
    set_track_subjects(db_session, track.id, [sub.id])

    students = []
    for i in range(10):
        st = create_student(
            db_session,
            username=f"scale_st_{i}",
            password="Password123!",
            full_name=f"Scale Student {i}",
            grade="11" if i % 2 == 0 else "10",
        )
        assign_student_track(db_session, st.id, track.id)
        students.append(st)

    # Messaging conversations & mixed unread messages
    for i, st in enumerate(students):
        conv = get_or_create_conversation(db_session, student_id=st.id, tutor_id=tutor_user.id)
        send_message(db_session, conv.id, sender=st, content=f"First {i}")
        if i % 2 == 0:
            send_message(db_session, conv.id, sender=st, content=f"Unread follow-up {i}")
        else:
            send_message(db_session, conv.id, sender=tutor_user, content=f"Tutor reply {i}")

    # Practice exams with cross-student attempts
    p_exams = []
    for idx in range(4):
        pe = create_practice_exam(db_session, title=f"PE {idx}", grade="11", academic_track_id=track.id)
        db_session.add(
            PracticeExamBooklet(
                practice_exam_id=pe.id,
                title="Booklet 1",
                order_index=1,
                question_start=1,
                question_end=1,
                file_path="practice_booklets/dummy.pdf",
                file_name="dummy.pdf",
            )
        )
        p_exams.append(pe)
    db_session.add(PracticeExamAssignment(practice_exam_id=p_exams[0].id, student_id=students[1].id))
    for st in students[2:]:
        db_session.add(
            StudentPracticeAttempt(
                practice_exam_id=p_exams[0].id,
                student_id=st.id,
                status="COMPLETED",
                overall_percentage=75.0,
            )
        )
    db_session.commit()

    # External exam series & assignments
    ex = create_exam(db_session, title="Scale Exam Series")
    sess = create_exam_session(
        db_session,
        exam_id=ex.id,
        exam_date=date.today(),
        track_subjects_map={track.id: [sub.id]},
    )
    assign_exam_series_to_students(db_session, ex.id, [s.id for s in students])
    for st in students[1:5]:
        submit_student_exam_result(
            db_session,
            exam_session_id=sess.id,
            student_id=st.id,
            subject_data=[{"subject_id": sub.id, "correct_answers": 10, "incorrect_answers": 0, "percentage": 50.0}],
        )

    queries: list[str] = []

    def _count_sql(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", _count_sql)
    try:
        queries.clear()
        convs = list_tutor_conversations(db_session, tutor_id=tutor_user.id)
        conv_queries = len(queries)
        assert len(convs) == 10
        assert sum(item["unread_count"] for item in convs) == 15
        assert conv_queries <= 4

        queries.clear()
        incompat = get_all_series_incompatible_students(db_session)
        incompat_queries = len(queries)
        assert len(incompat) == 10  # no grade_track_configs created on ex
        assert incompat_queries <= 3

        queries.clear()
        avail_pe = get_student_available_practice_exams(db_session, students[0])
        pe_queries = len(queries)
        assert len(avail_pe) == 4
        assert all(pe.latest_attempt is None for pe in avail_pe)
        assert pe_queries <= 4

        queries.clear()
        avail_ext = get_student_available_exams(db_session, students[0])
        ext_queries = len(queries)
        assert len(avail_ext["upcoming"]) == 1
        assert avail_ext["upcoming"][0]["has_submitted"] is False
        assert ext_queries <= 7
    finally:
        event.remove(db_session.bind, "before_cursor_execute", _count_sql)

    # Confirm single poller per role in templates
    base_html = Path("app/templates/base.html").read_text(encoding="utf-8")
    drawer_html = Path("app/templates/partials/mobile_nav_drawer.html").read_text(encoding="utf-8")
    combined = base_html + "\n" + drawer_html
    assert combined.count('hx-get="/tutor/messages/unread-count"') == 1
    assert combined.count('hx-get="/student/chat/unread-count"') == 1
    assert 'data-sync-badge="tutor-unread-badge"' in drawer_html
    assert 'data-sync-badge="student-unread-badge"' in base_html
    assert 'data-sync-badge="student-unread-badge"' in drawer_html
