import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from app.core.timezone import get_timezone
from app.models.settings import TelegramBackupSettings
from app.services.telegram_backup_service import (
    TelegramBackupValidationError,
    compute_next_run_at,
    create_and_deliver_manual_backup,
    decrypt_secret,
    deliver_backup_to_telegram,
    encrypt_secret,
    get_or_create_telegram_settings,
    mask_bot_token,
    run_scheduled_backup_tick,
    sanitize_telegram_error,
    send_test_message,
    split_file_for_telegram,
    update_telegram_settings,
)


def test_encrypt_decrypt_roundtrip_and_tamper():
    token = "123456789:AAH_super_secret_bot_token_XYZ"
    blob1 = encrypt_secret(token, secret_key="unit-test-secret-key-min-32-characters")
    blob2 = encrypt_secret(token, secret_key="unit-test-secret-key-min-32-characters")
    assert blob1 != blob2
    assert token not in blob1
    assert decrypt_secret(blob1, secret_key="unit-test-secret-key-min-32-characters") == token

    # Tampering with last character must fail MAC verification
    tampered = blob1[:-1] + ("A" if blob1[-1] != "A" else "B")
    with pytest.raises(ValueError):
        decrypt_secret(tampered, secret_key="unit-test-secret-key-min-32-characters")


def test_mask_bot_token_and_error_sanitization():
    assert mask_bot_token(None) is None
    assert mask_bot_token("   ") is None
    assert mask_bot_token("short") == "••••••••"
    assert mask_bot_token("123456789:AAH_secret_XYZ9") == "••••XYZ9"

    tok = "987654321:AAFakeSecretToken99"
    err = f"Client error for url https://api.telegram.org/bot{tok}/sendDocument with token {tok}"
    sanitized = sanitize_telegram_error(err, tok)
    assert tok not in sanitized
    assert "bot[REDACTED]" in sanitized
    assert "[REDACTED]" in sanitized


def test_split_file_for_telegram_under_and_over_limit(tmp_path: Path):
    src = tmp_path / "valhalla_backup_test.tar.gz"
    payload = b"ABCD1234" * 300  # 2400 bytes
    src.write_bytes(payload)

    # Under limit -> returns original file
    single = split_file_for_telegram(src, tmp_path / "parts_single", max_part_bytes=4096)
    assert single == [src]

    # Over limit -> splits into 3 parts of <= 1000 bytes
    parts_dir = tmp_path / "parts_multi"
    parts = split_file_for_telegram(src, parts_dir, max_part_bytes=1000)
    assert [p.name for p in parts] == [
        "valhalla_backup_test.tar.gz.part001",
        "valhalla_backup_test.tar.gz.part002",
        "valhalla_backup_test.tar.gz.part003",
    ]
    assert [p.stat().st_size for p in parts] == [1000, 1000, 400]

    reassembled = b"".join(p.read_bytes() for p in parts)
    assert reassembled == payload
    assert hashlib.sha256(reassembled).hexdigest() == hashlib.sha256(payload).hexdigest()


def test_deliver_backup_disabled_and_misconfigured_never_raises(db_session, tmp_path: Path):
    archive = tmp_path / "backup.tar.gz"
    archive.write_bytes(b"backup-bytes")

    # Disabled by default -> skipped cleanly
    res = deliver_backup_to_telegram(db_session, archive)
    assert res.delivered is False
    assert res.skipped is True

    # Enabled without token/chat_id -> fails cleanly without raising
    update_telegram_settings(db_session, enabled=True, chat_id="", new_bot_token=None)
    res2 = deliver_backup_to_telegram(db_session, archive)
    assert res2.delivered is False
    assert res2.skipped is False
    rec = get_or_create_telegram_settings(db_session)
    assert rec.last_backup_success is False
    assert rec.last_backup_at is not None


def test_deliver_backup_split_upload_and_status_with_mock_transport(db_session, tmp_path: Path):
    token = "111222333:AA_Test_Bot_Token_1234"
    update_telegram_settings(
        db_session,
        enabled=True,
        chat_id="-100999888777",
        new_bot_token=token,
    )

    archive = tmp_path / "valhalla_backup_20261127T120000Z.tar.gz.enc"
    archive.write_bytes(b"X" * 2500)

    captured_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("latin1", errors="ignore")
        captured_calls.append((str(request.url), body))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(captured_calls)}})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        res = deliver_backup_to_telegram(
            db_session,
            archive,
            max_part_bytes=1000,
            client=client,
        )

    assert res.delivered is True
    assert res.parts_sent == 3
    assert len(captured_calls) == 3
    assert "[Part 1/3]" in captured_calls[0][1]
    assert "[Part 2/3]" in captured_calls[1][1]
    assert "[Part 3/3]" in captured_calls[2][1]
    assert "part001" in captured_calls[0][1]

    rec = get_or_create_telegram_settings(db_session)
    assert rec.last_backup_success is True
    assert "3 part(s)" in (rec.last_backup_message or "")


def test_deliver_backup_network_failure_sanitizes_token(db_session, tmp_path: Path):
    token = "555666777:AA_Secret_Leak_Check_99"
    update_telegram_settings(
        db_session,
        enabled=True,
        chat_id="12345",
        new_bot_token=token,
    )
    archive = tmp_path / "b.tar.gz"
    archive.write_bytes(b"hello")

    def failing_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"Failed connecting to https://api.telegram.org/bot{token}/sendDocument")

    with httpx.Client(transport=httpx.MockTransport(failing_handler)) as client:
        res = deliver_backup_to_telegram(db_session, archive, client=client)

    assert res.delivered is False
    assert token not in res.message
    rec = get_or_create_telegram_settings(db_session)
    assert rec.last_backup_success is False
    assert token not in (rec.last_backup_message or "")


def test_send_test_message_success_and_failure():
    ok_transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True}))
    with httpx.Client(transport=ok_transport) as client:
        ok, msg = send_test_message("123:ABC", "999", client=client)
    assert ok is True
    assert "delivered" in msg.lower()

    err_transport = httpx.MockTransport(
        lambda req: httpx.Response(401, json={"ok": False, "description": "Unauthorized"})
    )
    with httpx.Client(transport=err_transport) as client:
        ok2, msg2 = send_test_message("123:ABC", "999", client=client)
    assert ok2 is False
    assert "Unauthorized" in msg2


def test_create_and_deliver_manual_backup_with_mock_transport(db_session, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path / "uploads"))
    (tmp_path / "uploads" / "practice_booklets").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads" / "practice_booklets" / "sample.pdf").write_bytes(b"%PDF-1.4 sample")

    update_telegram_settings(
        db_session,
        enabled=True,
        chat_id="123456",
        new_bot_token="999888777:AA_Manual_Backup_Token",
    )

    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True}))
    with httpx.Client(transport=transport) as client:
        res = create_and_deliver_manual_backup(db_session, client=client)

    assert res.delivered is True
    assert res.parts_sent == 1


def test_compute_next_run_at_interval_hours_and_days():
    ref = datetime(2026, 11, 27, 10, 0, tzinfo=timezone.utc)

    rec_disabled = TelegramBackupSettings(schedule_enabled=False)
    assert compute_next_run_at(rec_disabled, ref) is None

    rec_hours = TelegramBackupSettings(
        schedule_enabled=True,
        schedule_mode="interval",
        interval_value=6,
        interval_unit="hours",
    )
    assert compute_next_run_at(rec_hours, ref) == ref + timedelta(hours=6)

    rec_days = TelegramBackupSettings(
        schedule_enabled=True,
        schedule_mode="interval",
        interval_value=3,
        interval_unit="days",
    )
    assert compute_next_run_at(rec_days, ref) == ref + timedelta(days=3)


def test_compute_next_run_at_daily_midnight_asia_tehran():
    tehran = get_timezone()

    # Before midnight in Asia/Tehran (23:30 local) -> next midnight is 30 mins later (next calendar day 00:00)
    before_midnight_local = datetime(2026, 11, 27, 23, 30, tzinfo=tehran)
    next_utc = compute_next_run_at(
        TelegramBackupSettings(schedule_enabled=True, schedule_mode="daily", daily_time="00:00"),
        before_midnight_local.astimezone(timezone.utc),
    )
    assert next_utc is not None
    assert next_utc.astimezone(tehran) == datetime(2026, 11, 28, 0, 0, tzinfo=tehran)

    # Just after midnight in Asia/Tehran (00:05 local) -> next midnight is tomorrow (2026-11-29 00:00)
    after_midnight_local = datetime(2026, 11, 28, 0, 5, tzinfo=tehran)
    next_utc2 = compute_next_run_at(
        TelegramBackupSettings(schedule_enabled=True, schedule_mode="daily", daily_time="00:00"),
        after_midnight_local.astimezone(timezone.utc),
    )
    assert next_utc2 is not None
    assert next_utc2.astimezone(tehran) == datetime(2026, 11, 29, 0, 0, tzinfo=tehran)


def test_compute_next_run_at_and_update_validation():
    ref = datetime(2026, 11, 27, 10, 0, tzinfo=timezone.utc)

    with pytest.raises(TelegramBackupValidationError):
        compute_next_run_at(
            TelegramBackupSettings(schedule_enabled=True, schedule_mode="daily", daily_time="25:00"),
            ref,
        )

    with pytest.raises(TelegramBackupValidationError):
        compute_next_run_at(
            TelegramBackupSettings(schedule_enabled=True, schedule_mode="daily", daily_time="bad"),
            ref,
        )

    with pytest.raises(TelegramBackupValidationError):
        compute_next_run_at(
            TelegramBackupSettings(
                schedule_enabled=True,
                schedule_mode="interval",
                interval_value=0,
                interval_unit="hours",
            ),
            ref,
        )

    with pytest.raises(TelegramBackupValidationError):
        compute_next_run_at(
            TelegramBackupSettings(
                schedule_enabled=True,
                schedule_mode="interval",
                interval_value=2,
                interval_unit="weeks",
            ),
            ref,
        )

    with pytest.raises(TelegramBackupValidationError):
        compute_next_run_at(
            TelegramBackupSettings(schedule_enabled=True, schedule_mode="cron"),
            ref,
        )


def test_scheduled_backup_tick_advances_next_run_even_on_failure(db_session, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path / "uploads"))
    (tmp_path / "uploads").mkdir(parents=True, exist_ok=True)

    rec = update_telegram_settings(
        db_session,
        enabled=True,
        chat_id="123456",
        new_bot_token="999888777:AA_Scheduled_Token",
        schedule_enabled=True,
        schedule_mode="interval",
        interval_value=4,
        interval_unit="hours",
    )
    assert rec.next_run_at is not None

    # Not due yet -> should skip
    assert run_scheduled_backup_tick(db_session) is False

    # Force due in the past
    past = datetime(2020, 1, 1, 0, 0, tzinfo=timezone.utc)
    rec.next_run_at = past
    db_session.commit()

    def fail_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"ok": False, "description": "Internal error"})

    with httpx.Client(transport=httpx.MockTransport(fail_handler)) as client:
        ran = run_scheduled_backup_tick(db_session, client=client)

    assert ran is True
    db_session.refresh(rec)
    assert rec.last_backup_success is False
    assert rec.next_run_at is not None
    assert rec.next_run_at.replace(tzinfo=timezone.utc) > past
