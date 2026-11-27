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
from pathlib import Path
from typing import List, Optional, Tuple

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.storage import get_upload_base_path
from app.core.timezone import now_utc
from app.models.base import Base
from app.models.settings import TelegramBackupSettings

logger = logging.getLogger(__name__)

# Leave 2 MB headroom below Telegram Bot API's 50 MB (52,428,800 B) limit for multipart framing.
TELEGRAM_MAX_PART_BYTES = 48 * 1024 * 1024
TELEGRAM_API_BASE = "https://api.telegram.org"
_TOKEN_PREFIX = "v1:"


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


def sanitize_telegram_error(message: str, bot_token: Optional[str] = None) -> str:
    """Redact bot tokens and Telegram bot URLs from error strings."""
    cleaned = re.sub(r"bot[0-9A-Za-z:_-]+", "bot[REDACTED]", str(message))
    if bot_token and bot_token.strip():
        cleaned = cleaned.replace(bot_token.strip(), "[REDACTED]")
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
        if pg_dump_bin and db_url.startswith("postgresql"):
            clean_url = db_url.replace("postgresql+psycopg2://", "postgresql://", 1)
            db_file = staging / "db.dump"
            subprocess.run(
                [pg_dump_bin, clean_url, "-F", "c", "-b", "--no-owner", "--no-privileges", "-f", str(db_file)],
                check=True,
                capture_output=True,
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
