import pytest
from typing import Generator
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.core.rate_limit import login_limiter
from app.main import app
from app.models.base import Base
from app.models.user import User, UserRole
from app.services.auth_service import create_session
from app.services.tutor_provision import provision_tutor
from app.services.user_service import create_student

# Shared in-memory SQLite engine for tests
TEST_SQLITE_URL = "sqlite:///:memory:"

engine_test = create_engine(
    TEST_SQLITE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine_test,
)


@pytest.fixture(autouse=True)
def setup_test_db() -> Generator[None, None, None]:
    """Create all tables before each test and drop them after."""
    Base.metadata.create_all(bind=engine_test)
    login_limiter.reset()
    yield
    Base.metadata.drop_all(bind=engine_test)
    login_limiter.reset()


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Provide a clean transactional database session."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """FastAPI TestClient with overridden get_db dependency."""
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def tutor_user(db_session: Session) -> User:
    """Create and return an active tutor."""
    return provision_tutor(
        db=db_session,
        username="headtutor",
        password="TutorSecretPassword123!",
        full_name="Head Tutor",
        email="tutor@valhalla.local",
    )


@pytest.fixture
def student_user(db_session: Session) -> User:
    """Create and return an active student."""
    return create_student(
        db=db_session,
        username="student1",
        full_name="Student One",
        password="StudentSecretPassword123!",
        email="student1@valhalla.local",
    )


@pytest.fixture
def tutor_session(db_session: Session, tutor_user: User):
    """Return raw session token and session record for tutor."""
    token, session_rec = create_session(db_session, tutor_user)
    return token, session_rec


@pytest.fixture
def student_session(db_session: Session, student_user: User):
    """Return raw session token and session record for student."""
    token, session_rec = create_session(db_session, student_user)
    return token, session_rec

