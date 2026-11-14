import pytest
from sqlalchemy import create_engine, text
from app.core.config import settings
from app.models.base import Base
from app.models.user import User, UserRole
from app.services.auth_service import create_session, get_user_and_session_by_token
from app.services.tutor_provision import provision_tutor


def is_postgres_available() -> bool:
    """Check if PostgreSQL server is running and accessible."""
    try:
        engine = create_engine(settings.sync_database_url, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.mark.skipif(not is_postgres_available(), reason="PostgreSQL service not reachable; run docker compose up db to execute PostgreSQL integration tests.")
def test_postgres_schema_and_session_lifecycle():
    """Integration test verifying schema creation and session operations directly on PostgreSQL."""
    pg_engine = create_engine(settings.sync_database_url)
    Base.metadata.create_all(bind=pg_engine)

    from sqlalchemy.orm import Session
    with Session(pg_engine) as session:
        # Provision tutor
        tutor = provision_tutor(
            db=session,
            username="pg_tutor",
            password="PgPassword123!",
            full_name="Postgres Tutor",
        )
        assert tutor.role == UserRole.TUTOR

        # Create session
        token, s_rec = create_session(session, tutor)
        assert s_rec.user_id == tutor.id

        # Validate session retrieval
        u, s = get_user_and_session_by_token(session, token)
        assert u is not None
        assert u.username == "pg_tutor"

        # Cleanup
        session.delete(s_rec)
        session.delete(tutor)
        session.commit()

