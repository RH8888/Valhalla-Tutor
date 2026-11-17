# Valhalla Tutor &mdash; Production Deployment Guide (Ubuntu)

This guide provides end-to-end instructions for deploying, updating, and maintaining Valhalla Tutor on an Ubuntu 22.04 / 24.04 LTS server.

---

## 1. System Architecture & Overview

* **Host-level Nginx**: Terminates TLS/HTTPS, enforces rate limiting on login routes, manages SSL via Certbot, and proxies requests to `127.0.0.1:8000`.
* **valhalla_web**: FastAPI + Uvicorn (2+ workers), non-root execution (`appuser:10001`), database connectivity checking, automatic migration handling, persistent uploads volume (`uploads_data`), and healthcheck monitoring via `/health/db`.
* **valhalla_db**: PostgreSQL 16 on private Docker network `valhalla_network` (never exposed to host or internet), persistent data in `postgres_data`, host backup mounting to `./backups`.

---

## 2. Server Prerequisites (Fresh Ubuntu Installation)

```bash
# 1. Update OS packages
sudo apt update && sudo apt upgrade -y

# 2. Install Docker & Docker Compose plugin
sudo apt install -y ca-certificates curl gnupg lsb-release
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 3. Add current user to docker group
sudo usermod -aG docker $USER
newgrp docker

# 4. Install host Nginx and Certbot
sudo apt install -y nginx certbot python3-certbot-nginx
```

---

## 3. Initial Project Setup

```bash
# 1. Clone repository to deployment location
cd /var/www  # or your preferred deployment directory
git clone <repository_url> valhalla-tutor
cd valhalla-tutor

# 2. Prepare environment configuration
cp .env.example .env

# 3. Generate secure secrets
# Generate SECRET_KEY
openssl rand -hex 32
# Generate POSTGRES_PASSWORD
openssl rand -base64 24

# 4. Edit .env and configure real credentials
nano .env
# Set ENVIRONMENT=production
# Set DEBUG=False
# Set POSTGRES_PASSWORD=<generated_db_password>
# Set SECRET_KEY=<generated_secret_key>

# 5. Create backups directory on host
mkdir -p backups
```

---

## 4. Host Nginx & SSL Configuration

```bash
# 1. Copy Nginx configuration template
sudo cp nginx/valhalla.conf /etc/nginx/sites-available/valhalla.conf

# 2. Edit domain name in configuration
sudo nano /etc/nginx/sites-available/valhalla.conf
# Replace 'your-domain.com' with your actual domain

# 3. Enable site configuration
sudo ln -s /etc/nginx/sites-available/valhalla.conf /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# 4. Obtain SSL certificate with Certbot
sudo certbot --nginx -d your-domain.com

# 5. Verify Nginx configuration and reload
sudo nginx -t
sudo systemctl reload nginx
```

---

## 5. Operations & Maintenance Runbook

### Deploy & Start Application
```bash
# Build image and start services in background
docker compose up -d --build

# Verify container statuses and healthchecks
docker compose ps
```

### Inspect Application Status & Health
```bash
# View live container logs
docker compose logs -f web

# Inspect database connectivity endpoint
curl -f http://127.0.0.1:8000/health/db

# View detailed healthcheck status
docker inspect --format='{{json .State.Health}}' valhalla_web
```

### Safe Application Update Workflow
```bash
# 1. Create a database backup BEFORE updating
mkdir -p backups
docker compose exec -T db pg_dump -U postgres -d valhalla_db -F c -b -v -f /var/lib/postgresql/backups/pre_update_$(date +%Y%m%d_%H%M%S).dump

# 2. Pull latest code
git pull origin main

# 3. Rebuild and restart containers (auto-migrates schema if AUTO_MIGRATE=true)
docker compose up -d --build

# 4. Verify deployment health
docker compose ps
curl -f http://127.0.0.1:8000/health/db
```

### Database Backup & Restore

```bash
# Backup database (Compressed custom format)
docker compose exec -T db pg_dump -U postgres -d valhalla_db -F c -b -v -f /var/lib/postgresql/backups/valhalla_$(date +%Y%m%d_%H%M%S).dump

# Restore database from a backup file
# WARNING: This overwrites target database data!
docker compose exec -T db pg_restore -U postgres -d valhalla_db -c -v /var/lib/postgresql/backups/<backup_filename>.dump
```

### Uploaded Files (Booklets & Report Cards) Backup & Restore

```bash
# Backup uploads volume to a compressed archive
docker compose exec -T web tar -czf - -C /app uploads > backups/uploads_$(date +%Y%m%d_%H%M%S).tar.gz

# Restore uploads archive into volume
docker compose exec -i web tar -xzf - -C /app < backups/<uploads_filename>.tar.gz
```

### Manual Database Migrations (When AUTO_MIGRATE=false)
```bash
# Run pending migrations
docker compose exec web alembic upgrade head

# Inspect current database revision
docker compose exec web alembic current

# View migration history
docker compose exec web alembic history
```
