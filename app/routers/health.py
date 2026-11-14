import logging
from fastapi import APIRouter, Response, status

from app.core.config import settings
from app.core.database import check_db_connectivity
from app.core.timezone import now_utc, to_local
from app.schemas.health import HealthCheckResponse, SimpleHealthResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=SimpleHealthResponse, summary="Basic liveness probe")
def liveness_check() -> SimpleHealthResponse:
    """Basic health check verifying the FastAPI server process is running."""
    return SimpleHealthResponse(
        status="ok",
        app_name=settings.APP_NAME,
    )


@router.get("/health/db", response_model=HealthCheckResponse, summary="Database connectivity and readiness probe")
def readiness_check(response: Response) -> HealthCheckResponse:
    """Readiness probe checking database connectivity and system clock synchronization."""
    db_connected, db_error = check_db_connectivity()
    utc_now = now_utc()
    local_now = to_local(utc_now)

    client_error_msg = None
    if not db_connected:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        # Log detailed exception server-side
        logger.error("Database health check failed: %s", db_error)
        # Never expose raw connection strings, hosts, ports or internal stack traces to clients
        client_error_msg = "Database connection unavailable"

    return HealthCheckResponse(
        status="healthy" if db_connected else "unhealthy",
        app_name=settings.APP_NAME,
        environment=settings.ENVIRONMENT,
        database_connected=db_connected,
        timezone=settings.DEFAULT_TIMEZONE,
        server_time_utc=utc_now,
        server_time_local=local_now.isoformat(),
        database_error=client_error_msg,
    )
