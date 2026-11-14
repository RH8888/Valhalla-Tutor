# Valhalla Tutor — Academic Planner

A monolithic server-rendered academic planning and student tracking system built with **FastAPI**, **PostgreSQL 16**, **SQLAlchemy 2.0**, and **Alembic**.

## Project Architecture & Tech Stack

- **Backend**: FastAPI with synchronous Uvicorn server processes.
- **Database**: PostgreSQL 16 (stored with timezone-aware `TIMESTAMPTZ` in UTC).
- **ORM & Migrations**: SQLAlchemy 2.0 with explicit Alembic naming conventions.
- **Frontend / Templating**: Jinja2 SSR augmented with HTMX (no Node.js build tooling required).
- **Configuration**: Pydantic Settings with `.env` file support.
- **Timezone**: UTC database persistence with configurable localized user timezones (default: `Asia/Tehran`).

## Quickstart

### 1. Environment Setup

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Review and adjust variables in `.env` if necessary.

### 2. Running with Docker Compose

Start the PostgreSQL 16 database and web service:
```bash
docker compose up -d
```

Check health:
- Liveness: `curl http://localhost:8000/health`
- Database Readiness: `curl http://localhost:8000/health/db`

Database backups are automatically mounted to `./backups` with persistent volume `postgres_data`.

### 3. Local Development Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Or on Windows: .\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Run database migrations
alembic upgrade head

# Start development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Running Automated Tests

```bash
pytest -v
```

## Health Check Endpoints

- `GET /health`: Basic process liveness probe.
- `GET /health/db`: Detailed readiness probe verifying PostgreSQL connectivity, server UTC clock, and local timezone conversions.

## Project Structure

```
├── app/
│   ├── core/           # Config, database engine, timezone utilities
│   ├── models/         # SQLAlchemy 2.0 models & base
│   ├── schemas/        # Pydantic request/response schemas
│   ├── services/       # Business logic domain services
│   ├── routers/        # FastAPI endpoints & view routes
│   ├── templates/      # Jinja2 HTML templates
│   └── static/         # CSS and JavaScript assets
├── alembic/            # Database migration scripts
├── backups/            # Mounted target for database backups
├── tests/              # Pytest automated test suite
├── docker-compose.yml  # PostgreSQL 16 & Web service definition
└── requirements.txt    # Pinned production dependencies
```

