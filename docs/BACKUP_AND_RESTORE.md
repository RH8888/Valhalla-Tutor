# Valhalla Tutor — Backup & Restore Operations Guide

This guide covers automated backups, optional encryption, retention pruning, and safe restore testing for a single-VPS Docker Compose deployment (`valhalla_db` + `valhalla_web` + `uploads_data`).

All backup archives are stored in `backups/` and are excluded from Git tracking via `.gitignore`.

---

## 1. Manual Backup

```bash
chmod +x scripts/backup.sh scripts/restore.sh

# Unencrypted backup (keeps at least 7 newest, prunes >14 days old)
./scripts/backup.sh

# Encrypted backup using a passphrase file (recommended for off-VPS sync)
openssl rand -base64 32 > /root/.valhalla_backup_key
chmod 600 /root/.valhalla_backup_key
./scripts/backup.sh --passphrase-file /root/.valhalla_backup_key
```

### What `backup.sh` Does
1. Acquires a lock (`backups/.backup.lock`) and writes to a temporary staging directory.
2. Captures a consistent MVCC snapshot via `pg_dump -F c` and verifies it with `pg_restore --list`.
3. Archives `/app/uploads` (`uploads.tar.gz`) and verifies it with `gzip -t` + `tar -tzf`.
4. Writes `metadata.txt` and `SHA256SUMS`, verifies checksums, packages `bundle.tar.gz` (optionally encrypting with `openssl enc -aes-256-cbc -pbkdf2`), and atomically moves it into `backups/`.
5. On any failure, removes all temporary/staging files so no partial backup is left behind.
6. After a successful backup, prunes backups older than `--keep-days` (default `14`) while always keeping at least `--keep-count` (default `7`) newest backups.

---

## 2. Scheduled Automation (Cron)

Add a daily cron job (e.g., 03:15 AM local time) using `crontab -e`:

```cron
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

15 3 * * * /var/www/valhalla-tutor/scripts/backup.sh --passphrase-file /root/.valhalla_backup_key --keep-days 14 --keep-count 7 >> /var/log/valhalla-backup.log 2>&1
```

> **Off-VPS Recommendation:** Sync `backups/` to remote object storage or another server after the cron job completes (e.g., `rclone sync` or `rsync` over SSH) so a VPS disk failure does not destroy your backups.

---

## 3. Restore & Safe Restore Testing

### Step 1: Verify Without Touching Live Data (`--dry-run`)
Always test a backup's decryption, SHA-256 manifest, `pg_restore --list`, and `uploads.tar.gz` integrity first:

```bash
./scripts/restore.sh --dry-run --passphrase-file /root/.valhalla_backup_key backups/valhalla_backup_<TIMESTAMP>.tar.gz.enc
```

### Step 2: Safe Full Restore Test (Recommended Monthly)
1. **Take a fresh pre-test backup** of the current live state:
   ```bash
   ./scripts/backup.sh --passphrase-file /root/.valhalla_backup_key
   ```
2. **Run restore** (prompts you to type `RESTORE`; pass `--yes` for non-interactive automation):
   ```bash
   ./scripts/restore.sh --passphrase-file /root/.valhalla_backup_key backups/valhalla_backup_<TIMESTAMP>.tar.gz.enc
   ```
   `restore.sh` verifies all checksums and archives **before** stopping `web`, restores PostgreSQL inside a single transaction (`--single-transaction --exit-on-error`), replaces `/app/uploads` from a staging directory inside the volume, restarts `web`, and polls `/health/db` until healthy.
3. **Spot-check** login, student plans, and an uploaded PDF/report card in the browser.

---

## 4. Off-Site Telegram Backup Delivery

1. Log in as a tutor and open **Backups** (`/tutor/settings/backup`).
2. Enter your **Target Chat ID** and **Telegram Bot Token**, enable delivery, and click **Save Settings**.
   - The Bot Token is encrypted at rest in PostgreSQL (`telegram_backup_settings`) and is never shown in plain text after saving.
3. Click **Test Connection** to verify delivery, or **Backup to Telegram Now** to trigger an immediate off-site snapshot.
4. Scheduled runs via `scripts/backup.sh` automatically stream each verified local backup to Telegram when enabled (pass `--no-telegram` to skip). If Telegram is disabled, misconfigured, or unreachable, the local backup still succeeds.

### Reassembling & Restoring Split Telegram Backups (>48 MB)
Telegram limits bot document uploads to 50 MB, so `telegram_backup_service` automatically splits larger archives into numbered parts (`.part001`, `.part002`, ...) with the full archive SHA-256 in the message caption.

To reassemble and restore from split parts downloaded from Telegram:
```bash
# 1. Concatenate parts in numeric order
cat valhalla_backup_<TIMESTAMP>.tar.gz.enc.part* > valhalla_backup_<TIMESTAMP>.tar.gz.enc

# 2. Verify SHA-256 matches the "Full SHA256" in the Telegram caption
sha256sum valhalla_backup_<TIMESTAMP>.tar.gz.enc

# 3. Verify and restore as usual
./scripts/restore.sh --dry-run --passphrase-file /root/.valhalla_backup_key valhalla_backup_<TIMESTAMP>.tar.gz.enc
./scripts/restore.sh --passphrase-file /root/.valhalla_backup_key valhalla_backup_<TIMESTAMP>.tar.gz.enc
```

