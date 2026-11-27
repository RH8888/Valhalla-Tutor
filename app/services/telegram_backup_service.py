import argparse
import base64
import gzip
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import httpx
from sqlalchemy import select, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.storage import get_upload_base_path
from app.core.timezone import get_timezone, now_utc, to_utc
from app.models.base import Base
from app.models.settings import TelegramBackupSettings

logger = logging.getLogger(__name__)

# Leave 2 MB headroom below Telegram Bot API's 50 MB (52,428,800 B) limit for multipart framing.
TELEGRAM_MAX_PART_BYTES = 48 * 1024 * 1024
TELEGRAM_API_BASE = "https://api.telegram.org"
_TOKEN_PREFIX = "v1:"
_SCHEDULER_ADVISORY_LOCK_ID = 88421001
_DAILY_TIME_RE = re.compile(r"^(\d{2}):(\d{2})$")


class TelegramBackupValidationError(ValueError):
    """Raised when Telegram backup schedule settings are invalid."""


def parse_daily_time(time_str: Optional[str]) -> Tuple[int, int]:
    """Validate and parse a 24-hour HH:MM string."""
    raw = (time_str or "").strip()
    m = _DAILY_TIME_RE.match(raw)
    if not m:
        raise TelegramBackupValidationError("Daily backup time must be in HH:MM (24-hour) format.")
    hour, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise TelegramBackupValidationError("Daily backup time must be between 00:00 and 23:59.")
    return hour, minute


def compute_next_run_at(
    rec: TelegramBackupSettings,
    reference_utc: Optional[datetime] = None,
) -> Optional[datetime]:
    """Compute the next scheduled UTC run time in Asia/Tehran or interval mode."""
    if not rec.schedule_enabled:
        return None

    now = to_utc(reference_utc) if reference_utc is not None else now_utc()
    mode = (rec.schedule_mode or "daily").strip().lower()

    if mode == "interval":
        try:
            val = int(rec.interval_value)
        except (TypeError, ValueError):
            raise TelegramBackupValidationError("Backup interval must be a whole number of at least 1.")
        if val < 1:
            raise TelegramBackupValidationError("Backup interval must be at least 1.")
        unit = (rec.interval_unit or "hours").strip().lower()
        if unit == "hours":
            return now + timedelta(hours=val)
        if unit == "days":
            return now + timedelta(days=val)
        raise TelegramBackupValidationError("Backup interval unit must be 'hours' or 'days'.")

    if mode == "daily":
        hour, minute = parse_daily_time(rec.daily_time)
        tz = get_timezone()
        local_now = now.astimezone(tz)
        candidate_local = datetime.combine(local_now.date(), dt_time(hour, minute), tzinfo=tz)
        if candidate_local <= local_now:
            candidate_local = datetime.combine(
                local_now.date() + timedelta(days=1),
                dt_time(hour, minute),
                tzinfo=tz,
            )
        return candidate_local.astimezone(timezone.utc)

    raise TelegramBackupValidationError("Schedule mode must be 'interval' or 'daily'.")


@dataclass
class TelegramDeliveryResult:
    delivered: bool
    skipped: bool
    message: str
    parts_sent: int = 0


def _derive_keys(secret: str) -> Tuple[bytes, bytes]:
    raw = secret.encode("utf-8")
    enc_key = hmac.new(raw, b"valhalla-telegram-token-enc-v1", hashlib.sha256).digest()
    mac_key = hmac.new(raw, b"valhalla-telegram-token-mac-v1", hashlib.sha256).digest()
    return enc_key, mac_key


def _keystream_block(enc_key: bytes, nonce: bytes, counter: int) -> bytes:
    return hmac.new(enc_key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()


def _xor_stream(enc_key: bytes, nonce: bytes, data: bytes) -> bytes:
    out = bytearray(len(data))
    offset = 0
    counter = 0
    while offset < len(data):
        block = _keystream_block(enc_key, nonce, counter)
        chunk_len = min(len(block), len(data) - offset)
        for i in range(chunk_len):
            out[offset + i] = data[offset + i] ^ block[i]
        offset += chunk_len
        counter += 1
    return bytes(out)


def encrypt_secret(plaintext: str, secret_key: Optional[str] = None) -> str:
    """Encrypt a secret string using HMAC-SHA256 CTR + Encrypt-then-MAC."""
    if not plaintext:
        raise ValueError("Cannot encrypt empty secret")
    enc_key, mac_key = _derive_keys(secret_key or settings.SECRET_KEY)
    nonce = os.urandom(16)
    ciphertext = _xor_stream(enc_key, nonce, plaintext.encode("utf-8"))
    tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    payload = base64.urlsafe_b64encode(nonce + ciphertext + tag).decode("ascii")
    return f"{_TOKEN_PREFIX}{payload}"


def decrypt_secret(token_blob: str, secret_key: Optional[str] = None) -> str:
    """Verify MAC and decrypt a secret encrypted with encrypt_secret."""
    if not token_blob or not token_blob.startswith(_TOKEN_PREFIX):
        raise ValueError("Unsupported encrypted secret format")
    raw = base64.urlsafe_b64decode(token_blob[len(_TOKEN_PREFIX):].encode("ascii"))
    if len(raw) < 16 + 32 + 1:
        raise ValueError("Corrupted encrypted secret")
    nonce = raw[:16]
    tag = raw[-32:]
    ciphertext = raw[16:-32]
    enc_key, mac_key = _derive_keys(secret_key or settings.SECRET_KEY)
    expected_tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected_tag):
        raise ValueError("Encrypted secret integrity check failed")
    plaintext_bytes = _xor_stream(enc_key, nonce, ciphertext)
    return plaintext_bytes.decode("utf-8")


def mask_bot_token(token: Optional[str]) -> Optional[str]:
    """Return a safe masked representation of a Telegram bot token."""
    if not token:
        return None
    stripped = token.strip()
    if not stripped:
        return None
    if len(stripped) < 8:
        return "••••••••"
    return f"••••{stripped[-4:]}"


_DB_CRED_URL_RE = re.compile(
    r"(postgres(?:ql)?(?:\+[A-Za-z0-9_]+)?://[^:\s@/]+:)[^\s/]+(@)"
)


def _extract_db_password() -> Optional[str]:
    try:
        url_pwd = make_url(settings.sync_database_url).password
    except Exception:
        url_pwd = None
    return url_pwd or settings.POSTGRES_PASSWORD or None


def sanitize_telegram_error(message: str, bot_token: Optional[str] = None) -> str:
    """Redact bot tokens, Telegram bot URLs, and DB credentials from error strings."""
    cleaned = re.sub(r"bot[0-9A-Za-z:_-]+", "bot[REDACTED]", str(message))
    cleaned = _DB_CRED_URL_RE.sub(r"\1[REDACTED]\2", cleaned)
    if bot_token and bot_token.strip():
        cleaned = cleaned.replace(bot_token.strip(), "[REDACTED]")
    db_pwd = _extract_db_password()
    if db_pwd and len(db_pwd) >= 6 and db_pwd.lower() not in ("postgres", "postgresql"):
        cleaned = cleaned.replace(db_pwd, "[REDACTED]")
    return cleaned[:480]


def get_or_create_telegram_settings(db: Session) -> TelegramBackupSettings:
    rec = db.execute(
        select(TelegramBackupSettings).where(TelegramBackupSettings.singleton_key == "default")
    ).scalar_one_or_none()
    if rec is None:
        rec = TelegramBackupSettings(singleton_key="default", enabled=False)
        db.add(rec)
        db.commit()
        db.refresh(rec)
    return rec


def update_telegram_settings(
    db: Session,
    *,
    enabled: bool,
    chat_id: Optional[str],
    new_bot_token: Optional[str] = None,
    clear_bot_token: bool = False,
    schedule_enabled: Optional[bool] = None,
    schedule_mode: Optional[str] = None,
    interval_value: Optional[int] = None,
    interval_unit: Optional[str] = None,
    daily_time: Optional[str] = None,
) -> TelegramBackupSettings:
    rec = get_or_create_telegram_settings(db)
    rec.enabled = bool(enabled)
    clean_chat = (chat_id or "").strip()
    rec.chat_id = clean_chat or None

    if clear_bot_token:
        rec.encrypted_bot_token = None
        rec.bot_token_mask = None
    elif new_bot_token is not None and new_bot_token.strip():
        clean_tok = new_bot_token.strip()
        rec.encrypted_bot_token = encrypt_secret(clean_tok)
        rec.bot_token_mask = mask_bot_token(clean_tok)

    schedule_touched = any(
        arg is not None
        for arg in (schedule_enabled, schedule_mode, interval_value, interval_unit, daily_time)
    )
    if schedule_touched:
        if schedule_enabled is not None:
            rec.schedule_enabled = bool(schedule_enabled)
        if schedule_mode is not None:
            mode_clean = schedule_mode.strip().lower()
            if mode_clean not in ("interval", "daily"):
                raise TelegramBackupValidationError("Schedule mode must be 'interval' or 'daily'.")
            rec.schedule_mode = mode_clean
        if interval_value is not None:
            if int(interval_value) < 1:
                raise TelegramBackupValidationError("Backup interval must be at least 1.")
            rec.interval_value = int(interval_value)
        if interval_unit is not None:
            unit_clean = interval_unit.strip().lower()
            if unit_clean not in ("hours", "days"):
                raise TelegramBackupValidationError("Backup interval unit must be 'hours' or 'days'.")
            rec.interval_unit = unit_clean
        if daily_time is not None:
            hour, minute = parse_daily_time(daily_time)
            rec.daily_time = f"{hour:02d}:{minute:02d}"

        rec.next_run_at = compute_next_run_at(rec)

    rec.updated_at = now_utc()
    db.commit()
    db.refresh(rec)
    return rec


def _get_decrypted_token(rec: TelegramBackupSettings) -> Optional[str]:
    if not rec.encrypted_bot_token:
        return None
    return decrypt_secret(rec.encrypted_bot_token)


def _record_status(
    db: Session,
    rec: TelegramBackupSettings,
    *,
    success: bool,
    message: str,
) -> None:
    rec.last_backup_at = now_utc()
    rec.last_backup_success = success
    rec.last_backup_message = sanitize_telegram_error(message)[:500]
    rec.updated_at = now_utc()
    db.commit()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def split_file_for_telegram(
    file_path: Path,
    output_dir: Path,
    max_part_bytes: int = TELEGRAM_MAX_PART_BYTES,
) -> List[Path]:
    """
    Split file_path into <= max_part_bytes parts if it exceeds max_part_bytes.
    Returns [file_path] if no split is needed, or [part001, part002, ...].
    """
    if max_part_bytes <= 0:
        raise ValueError("max_part_bytes must be positive")
    total_size = file_path.stat().st_size
    if total_size <= max_part_bytes:
        return [file_path]

    output_dir.mkdir(parents=True, exist_ok=True)
    parts: List[Path] = []
    part_idx = 1
    chunk_size = min(1024 * 1024, max_part_bytes)

    with open(file_path, "rb") as src:
        while True:
            part_path = output_dir / f"{file_path.name}.part{part_idx:03d}"
            written = 0
            with open(part_path, "wb") as dst:
                while written < max_part_bytes:
                    to_read = min(chunk_size, max_part_bytes - written)
                    data = src.read(to_read)
                    if not data:
                        break
                    dst.write(data)
                    written += len(data)
            if written == 0:
                if part_path.exists():
                    part_path.unlink()
                break
            parts.append(part_path)
            part_idx += 1

    return parts


def send_test_message(
    bot_token: str,
    chat_id: str,
    client: Optional[httpx.Client] = None,
) -> Tuple[bool, str]:
    """Send a test message via Telegram Bot API."""
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "✅ Valhalla Tutor: Telegram backup connection test succeeded.",
    }
    own_client = client is None
    http_client = client or httpx.Client(timeout=15.0)
    try:
        resp = http_client.post(url, json=payload)
        data = {}
        try:
            data = resp.json()
        except Exception:
            pass
        if resp.status_code == 200 and data.get("ok") is True:
            return True, "Test message delivered to Telegram."
        desc = data.get("description") or f"HTTP {resp.status_code}"
        return False, sanitize_telegram_error(f"Telegram API error: {desc}", bot_token)
    except Exception as exc:
        return False, sanitize_telegram_error(f"Connection failed: {exc}", bot_token)
    finally:
        if own_client:
            http_client.close()


def test_saved_telegram_connection(
    db: Session,
    client: Optional[httpx.Client] = None,
) -> Tuple[bool, str]:
    rec = get_or_create_telegram_settings(db)
    if not rec.chat_id:
        return False, "Target Chat ID is not configured."
    try:
        bot_token = _get_decrypted_token(rec)
    except Exception:
        return False, "Saved Bot Token could not be decrypted. Please re-enter it."
    if not bot_token:
        return False, "Telegram Bot Token is not configured."
    return send_test_message(bot_token, rec.chat_id, client=client)


def _send_document_part(
    http_client: httpx.Client,
    bot_token: str,
    chat_id: str,
    part_path: Path,
    caption: str,
) -> None:
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendDocument"
    with open(part_path, "rb") as f:
        resp = http_client.post(
            url,
            data={"chat_id": chat_id, "caption": caption[:1024]},
            files={"document": (part_path.name, f, "application/octet-stream")},
        )
    data = {}
    try:
        data = resp.json()
    except Exception:
        pass
    if resp.status_code != 200 or data.get("ok") is not True:
        desc = data.get("description") or f"HTTP {resp.status_code}"
        raise RuntimeError(f"Telegram upload failed for {part_path.name}: {desc}")


def deliver_backup_to_telegram(
    db: Session,
    backup_path: Path,
    *,
    max_part_bytes: int = TELEGRAM_MAX_PART_BYTES,
    client: Optional[httpx.Client] = None,
) -> TelegramDeliveryResult:
    """
    Deliver a backup archive to Telegram, splitting if > max_part_bytes.
    Never raises on disabled, misconfigured, or network/API failures.
    """
    rec = get_or_create_telegram_settings(db)
    if not rec.enabled:
        return TelegramDeliveryResult(
            delivered=False,
            skipped=True,
            message="Telegram backup delivery is disabled.",
        )

    if not backup_path.exists() or not backup_path.is_file():
        msg = f"Backup file not found: {backup_path.name}"
        _record_status(db, rec, success=False, message=msg)
        return TelegramDeliveryResult(delivered=False, skipped=False, message=msg)

    if not rec.chat_id:
        msg = "Telegram Chat ID is missing."
        _record_status(db, rec, success=False, message=msg)
        return TelegramDeliveryResult(delivered=False, skipped=False, message=msg)

    bot_token: Optional[str] = None
    try:
        bot_token = _get_decrypted_token(rec)
    except Exception:
        msg = "Saved Bot Token could not be decrypted."
        _record_status(db, rec, success=False, message=msg)
        return TelegramDeliveryResult(delivered=False, skipped=False, message=msg)

    if not bot_token:
        msg = "Telegram Bot Token is missing."
        _record_status(db, rec, success=False, message=msg)
        return TelegramDeliveryResult(delivered=False, skipped=False, message=msg)

    own_client = client is None
    http_client = client or httpx.Client(timeout=120.0)
    try:
        total_size = backup_path.stat().st_size
        full_sha = _sha256_file(backup_path)
        with tempfile.TemporaryDirectory() as tmp_dir:
            parts = split_file_for_telegram(
                backup_path,
                Path(tmp_dir),
                max_part_bytes=max_part_bytes,
            )
            total_parts = len(parts)
            for idx, part_path in enumerate(parts, start=1):
                if total_parts == 1:
                    caption = (
                        f"Valhalla Tutor Backup\n"
                        f"File: {backup_path.name}\n"
                        f"Size: {total_size} bytes\n"
                        f"SHA256: {full_sha}"
                    )
                else:
                    caption = (
                        f"Valhalla Tutor Backup [Part {idx}/{total_parts}]\n"
                        f"Archive: {backup_path.name} ({total_size} bytes)\n"
                        f"Full SHA256: {full_sha}\n"
                        f"Reassemble: cat {backup_path.name}.part* > {backup_path.name}"
                    )
                _send_document_part(
                    http_client,
                    bot_token,
                    rec.chat_id,
                    part_path,
                    caption,
                )

        ok_msg = f"Delivered {backup_path.name} in {total_parts} part(s) ({total_size} bytes)."
        _record_status(db, rec, success=True, message=ok_msg)
        return TelegramDeliveryResult(
            delivered=True,
            skipped=False,
            message=ok_msg,
            parts_sent=total_parts,
        )
    except Exception as exc:
        err_msg = sanitize_telegram_error(str(exc), bot_token)
        logger.warning("Telegram backup delivery failed: %s", err_msg)
        _record_status(db, rec, success=False, message=err_msg)
        return TelegramDeliveryResult(
            delivered=False,
            skipped=False,
            message=err_msg,
        )
    finally:
        if own_client:
            http_client.close()


def _export_db_fallback_json_gz(db: Session, dest_path: Path) -> None:
    """Consistent ORM-level table export when pg_dump is not installed in the web container."""
    payload = {}
    for table in Base.metadata.sorted_tables:
        rows = db.execute(table.select()).mappings().all()
        payload[table.name] = [
            {k: (v.isoformat() if hasattr(v, "isoformat") else str(v) if v is not None else None) for k, v in dict(r).items()}
            for r in rows
        ]
    with gzip.open(dest_path, "wt", encoding="utf-8") as gz:
        json.dump(payload, gz, ensure_ascii=False)


def create_and_deliver_manual_backup(
    db: Session,
    *,
    max_part_bytes: int = TELEGRAM_MAX_PART_BYTES,
    client: Optional[httpx.Client] = None,
) -> TelegramDeliveryResult:
    """Create a snapshot bundle from the running app and deliver it to Telegram."""
    rec = get_or_create_telegram_settings(db)
    if not rec.enabled:
        return TelegramDeliveryResult(
            delivered=False,
            skipped=True,
            message="Enable Telegram backup delivery first.",
        )

    ts = now_utc().strftime("%Y%m%dT%H%M%SZ")
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp_dir = Path(tmp_str)
        staging = tmp_dir / "staging"
        staging.mkdir(parents=True, exist_ok=True)

        pg_dump_bin = shutil.which("pg_dump")
        db_url = settings.sync_database_url
        is_postgres = db_url.startswith("postgresql") and (
            db.bind is None or db.bind.dialect.name == "postgresql"
        )
        if is_postgres:
            if not pg_dump_bin:
                msg = "pg_dump is unavailable in the web container; cannot create a restorable PostgreSQL backup (db.dump)."
                rec.last_backup_at = now_utc()
                rec.last_backup_success = False
                rec.last_backup_message = msg
                db.commit()
                return TelegramDeliveryResult(
                    delivered=False,
                    skipped=False,
                    message=msg,
                )
            parsed_url = make_url(db_url)
            db_file = staging / "db.dump"
            pg_dump_cmd = [pg_dump_bin]
            if parsed_url.host:
                pg_dump_cmd.extend(["-h", parsed_url.host])
            if parsed_url.port:
                pg_dump_cmd.extend(["-p", str(parsed_url.port)])
            if parsed_url.username:
                pg_dump_cmd.extend(["-U", parsed_url.username])
            if parsed_url.database:
                pg_dump_cmd.extend(["-d", parsed_url.database])
            pg_dump_cmd.extend(["-F", "c", "-b", "--no-owner", "--no-privileges", "-f", str(db_file)])

            pg_dump_env = os.environ.copy()
            if parsed_url.password:
                pg_dump_env["PGPASSWORD"] = parsed_url.password

            try:
                subprocess.run(
                    pg_dump_cmd,
                    check=True,
                    capture_output=True,
                    env=pg_dump_env,
                )
            except subprocess.CalledProcessError as exc:
                stderr_text = ""
                if exc.stderr:
                    stderr_text = (
                        exc.stderr.decode("utf-8", errors="replace")
                        if isinstance(exc.stderr, bytes)
                        else str(exc.stderr)
                    )
                raw_detail = f"pg_dump exited with code {exc.returncode}"
                if stderr_text.strip():
                    raw_detail = f"{raw_detail}: {stderr_text.strip()}"
                err_msg = sanitize_telegram_error(raw_detail, None)
                logger.warning("Telegram backup pg_dump failed: %s", err_msg)
                _record_status(db, rec, success=False, message=err_msg)
                return TelegramDeliveryResult(
                    delivered=False,
                    skipped=False,
                    message=err_msg,
                )
            db_artifact_name = "db.dump"
        else:
            db_file = staging / "db_export.json.gz"
            _export_db_fallback_json_gz(db, db_file)
            db_artifact_name = "db_export.json.gz"

        uploads_tar = staging / "uploads.tar.gz"
        uploads_base = get_upload_base_path()
        with tarfile.open(uploads_tar, "w:gz") as tf:
            tf.add(uploads_base, arcname="uploads")

        meta_file = staging / "metadata.txt"
        meta_file.write_text(
            f"timestamp_utc={ts}\nsource=manual_web_trigger\ndb_artifact={db_artifact_name}\n",
            encoding="utf-8",
        )

        sums_lines = []
        for fname in (db_artifact_name, "uploads.tar.gz", "metadata.txt"):
            sums_lines.append(f"{_sha256_file(staging / fname)}  {fname}")
        (staging / "SHA256SUMS").write_text("\n".join(sums_lines) + "\n", encoding="utf-8")

        bundle_path = tmp_dir / f"valhalla_backup_{ts}.tar.gz"
        with tarfile.open(bundle_path, "w:gz") as tf:
            for item in staging.iterdir():
                tf.add(item, arcname=item.name)

        return deliver_backup_to_telegram(
            db,
            bundle_path,
            max_part_bytes=max_part_bytes,
            client=client,
        )


def run_scheduled_backup_tick(
    db: Session,
    *,
    client: Optional[httpx.Client] = None,
) -> bool:
    """
    Check whether an automatic scheduled Telegram backup is due and execute it.
    Acquires a non-blocking PostgreSQL advisory lock before checking/advancing next_run_at
    so multi-worker deployments serialize cleanly without duplicating runs or wedging locks.
    Returns True if a scheduled backup run was attempted, False otherwise.
    """
    is_postgres = db.bind is not None and db.bind.dialect.name == "postgresql"
    lock_acquired = False
    if is_postgres:
        lock_acquired = bool(
            db.execute(
                text("SELECT pg_try_advisory_lock(:lock_id)"),
                {"lock_id": _SCHEDULER_ADVISORY_LOCK_ID},
            ).scalar()
        )
        if not lock_acquired:
            return False

    try:
        rec = get_or_create_telegram_settings(db)
        if not rec.schedule_enabled or not rec.enabled or not rec.chat_id or not rec.encrypted_bot_token:
            return False

        now = now_utc()
        if rec.next_run_at is None:
            rec.next_run_at = compute_next_run_at(rec, now)
            rec.updated_at = now
            db.commit()
            return False

        if now < to_utc(rec.next_run_at):
            return False

        try:
            create_and_deliver_manual_backup(db, client=client)
        except Exception as exc:
            err_msg = sanitize_telegram_error(str(exc), None)
            logger.warning("Scheduled Telegram backup failed: %s", err_msg)
            try:
                db.rollback()
                rec = get_or_create_telegram_settings(db)
                _record_status(db, rec, success=False, message=err_msg)
            except Exception:
                db.rollback()
                logger.exception("Failed to record failed scheduled Telegram backup status")
        finally:
            # Always advance next_run_at even on failure to prevent 60-second retry loops
            try:
                rec = get_or_create_telegram_settings(db)
                rec.next_run_at = compute_next_run_at(rec, now_utc())
                rec.updated_at = now_utc()
                db.commit()
            except Exception:
                db.rollback()
                raise

        return True
    finally:
        if is_postgres and lock_acquired:
            try:
                db.rollback()
            except Exception:
                pass
            try:
                db.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": _SCHEDULER_ADVISORY_LOCK_ID},
                )
                db.commit()
            except Exception:
                try:
                    db.invalidate()
                except Exception:
                    pass


def _cli_main() -> int:
    parser = argparse.ArgumentParser(description="Deliver a backup file to Telegram using DB settings.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", type=Path, help="Path to backup file")
    group.add_argument("--stdin", action="store_true", help="Read backup bytes from stdin")
    parser.add_argument("--filename", default="valhalla_backup.tar.gz", help="Filename when using --stdin")
    args = parser.parse_args()

    with SessionLocal() as db:
        if args.stdin:
            safe_name = Path(args.filename).name or "valhalla_backup.tar.gz"
            with tempfile.TemporaryDirectory() as tmp_dir:
                target = Path(tmp_dir) / safe_name
                with open(target, "wb") as f:
                    shutil.copyfileobj(sys.stdin.buffer, f)
                res = deliver_backup_to_telegram(db, target)
        else:
            res = deliver_backup_to_telegram(db, args.file)

    print(res.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli_main())
