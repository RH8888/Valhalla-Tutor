import hashlib
from pathlib import Path

import httpx
import pytest

from app.services.telegram_backup_service import (
    create_and_deliver_manual_backup,
    decrypt_secret,
    deliver_backup_to_telegram,
    encrypt_secret,
    get_or_create_telegram_settings,
    mask_bot_token,
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
