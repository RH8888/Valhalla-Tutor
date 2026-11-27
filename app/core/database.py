from typing import Generator, Optional, Tuple
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.base import Base

# SQLAlchemy 2.0 Engine (Synchronous per architecture specification)
_engine_kwargs = {
    "pool_pre_ping": True,
    "echo": settings.DEBUG,
}
if not settings.sync_database_url.startswith("sqlite"):
    _engine_kwargs.update(
        {
            "pool_size": settings.DB_POOL_SIZE,
            "max_overflow": settings.DB_MAX_OVERFLOW,
            "pool_timeout": settings.DB_POOL_TIMEOUT,
            "pool_recycle": settings.DB_POOL_RECYCLE,
        }
    )

engine = create_engine(settings.sync_database_url, **_engine_kwargs)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db() -> Generator[Session, None, None]:
    """Dependency that provides a database session and guarantees closure."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_connectivity() -> Tuple[bool, Optional[str]]:
    """
    Execute a low-level SELECT 1 query to verify database connectivity.
    Returns (True, None) on success or (False, error_message) on failure.
    """
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, None
    except Exception as exc:
        return False, str(exc)

