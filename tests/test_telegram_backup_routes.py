from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.dependencies import SESSION_COOKIE_NAME
from app.services.telegram_backup_service import (
    TelegramDeliveryResult,
    get_or_create_telegram_settings,
    update_telegram_settings,
)


def test_telegram_settings_requires_tutor_and_csrf(
    client: TestClient,
    tutor_session,
    student_session,
):
    # Unauthenticated -> 401
    resp = client.get("/tutor/settings/backup")
    assert resp.status_code == 401

    # Student -> 403
    s_token, s_rec = student_session
    resp_student = client.get(
        "/tutor/settings/backup",
        cookies={SESSION_COOKIE_NAME: s_token},
    )
    assert resp_student.status_code == 403

    # Tutor POST without CSRF -> 403
    t_token, t_rec = tutor_session
    resp_no_csrf = client.post(
        "/tutor/settings/backup",
        cookies={SESSION_COOKIE_NAME: t_token},
        data={"enabled": "1", "chat_id": "12345"},
        follow_redirects=False,
    )
    assert resp_no_csrf.status_code == 403


def test_telegram_settings_save_mask_and_clear_never_exposes_token(
    client: TestClient,
    db_session: Session,
    tutor_session,
):
    t_token, t_rec = tutor_session
    secret_bot_token = "123456789:AA_NEVER_SHOW_IN_HTML_9876"

    resp_save = client.post(
        "/tutor/settings/backup",
        cookies={SESSION_COOKIE_NAME: t_token},
        data={
            "csrf_token": t_rec.csrf_token,
            "enabled": "1",
            "chat_id": "-1001234567890",
            "bot_token": secret_bot_token,
        },
        follow_redirects=False,
    )
    assert resp_save.status_code == 303

    page = client.get(
        "/tutor/settings/backup",
        cookies={SESSION_COOKIE_NAME: t_token},
    )
    assert page.status_code == 200
    assert secret_bot_token not in page.text
    assert "••••9876" in page.text
    assert "-1001234567890" in page.text

    # Saving again without bot_token keeps existing encrypted token
    client.post(
        "/tutor/settings/backup",
        cookies={SESSION_COOKIE_NAME: t_token},
        data={
            "csrf_token": t_rec.csrf_token,
            "enabled": "1",
            "chat_id": "-1001234567890",
            "bot_token": "",
        },
        follow_redirects=False,
    )
    rec = get_or_create_telegram_settings(db_session)
    assert rec.encrypted_bot_token is not None
    assert rec.bot_token_mask == "••••9876"

    # Clearing token removes it
    client.post(
        "/tutor/settings/backup",
        cookies={SESSION_COOKIE_NAME: t_token},
        data={
            "csrf_token": t_rec.csrf_token,
            "enabled": "1",
            "chat_id": "-1001234567890",
            "clear_bot_token": "1",
        },
        follow_redirects=False,
    )
    db_session.refresh(rec)
    assert rec.encrypted_bot_token is None
    assert rec.bot_token_mask is None


def test_telegram_test_and_run_now_routes(
    client: TestClient,
    db_session: Session,
    tutor_session,
    monkeypatch,
):
    t_token, t_rec = tutor_session
    update_telegram_settings(
        db_session,
        enabled=True,
        chat_id="555123",
        new_bot_token="123456:AA_Mock_Token_4321",
    )

    monkeypatch.setattr(
        "app.routers.tutor_settings.test_saved_telegram_connection",
        lambda db: (True, "Test message delivered to Telegram."),
    )
    resp_test = client.post(
        "/tutor/settings/backup/test",
        cookies={SESSION_COOKIE_NAME: t_token},
        data={"csrf_token": t_rec.csrf_token},
        follow_redirects=False,
    )
    assert resp_test.status_code == 303
    assert "msg=" in resp_test.headers["location"]

    monkeypatch.setattr(
        "app.routers.tutor_settings.create_and_deliver_manual_backup",
        lambda db: TelegramDeliveryResult(
            delivered=True,
            skipped=False,
            message="Delivered valhalla_backup.tar.gz in 1 part(s).",
            parts_sent=1,
        ),
    )
    resp_run = client.post(
        "/tutor/settings/backup/run-now",
        cookies={SESSION_COOKIE_NAME: t_token},
        data={"csrf_token": t_rec.csrf_token},
        follow_redirects=False,
    )
    assert resp_run.status_code == 303
    assert "msg=" in resp_run.headers["location"]
