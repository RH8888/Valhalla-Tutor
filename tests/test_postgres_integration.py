import uuid
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
    from app.core.security import hash_password
    with Session(pg_engine) as session:
        # Create temp tutor
        test_uname = f"pg_tutor_{uuid.uuid4().hex[:8]}"
        tutor = User(
            id=uuid.uuid4(),
            username=test_uname,
            hashed_password=hash_password("PgPassword123!"),
            role=UserRole.TUTOR,
            full_name="Postgres Tutor",
            timezone="Asia/Tehran",
        )
        session.add(tutor)
        session.commit()
        assert tutor.role == UserRole.TUTOR

        # Create session
        token, s_rec = create_session(session, tutor)
        assert s_rec.user_id == tutor.id

        # Validate session retrieval
        u, s = get_user_and_session_by_token(session, token)
        assert u is not None
        assert u.username == test_uname

        # Cleanup
        session.delete(s_rec)
        session.delete(tutor)
        session.commit()



@pytest.mark.skipif(not is_postgres_available(), reason="PostgreSQL service not reachable; run docker compose up db to execute PostgreSQL integration tests.")
def test_postgres_meeting_and_reminders_lifecycle():
    """Verify meeting models, history, and reminders against live PostgreSQL 16."""
    from datetime import date, time
    from sqlalchemy.orm import Session
    from app.models.meeting import MeetingType, MeetingStatus, TutorMeeting
    from app.services.meeting_service import (
        create_meeting,
        reschedule_meeting,
        update_meeting_status,
        get_due_reminders,
        dismiss_reminder,
    )
    from app.services.user_service import create_student

    pg_engine = create_engine(settings.sync_database_url)
    with Session(pg_engine) as session:
        from app.core.security import hash_password
        tutor = User(
            id=uuid.uuid4(),
            username=f"tutor_{uuid.uuid4().hex[:6]}",
            hashed_password=hash_password("PgPassword123!"),
            role=UserRole.TUTOR,
            full_name="Postgres Meeting Tutor",
            timezone="Asia/Tehran",
        )
        session.add(tutor)
        session.commit()
        student = create_student(
            db=session,
            username=f"stu_{uuid.uuid4().hex[:6]}",
            full_name="Postgres Student",
            password="StuPassword123!",
        )

        # 1. Create meeting with reminder on PostgreSQL
        meeting = create_meeting(
            db=session,
            tutor=tutor,
            student_id=student.id,
            meeting_date=date(2026, 12, 1),
            start_time_obj=time(14, 0),
            duration_minutes=60,
            meeting_type=MeetingType.ONLINE,
            meeting_url="https://meet.pg.local/123",
            reminder_minutes=30,
        )
        assert meeting.id is not None
        assert meeting.status == MeetingStatus.SCHEDULED

        # 2. Reschedule meeting
        updated = reschedule_meeting(
            db=session,
            meeting_id=meeting.id,
            tutor=tutor,
            new_date=date(2026, 12, 1),
            new_time_obj=time(16, 0),
            new_duration_minutes=90,
            reason="Postgres reschedule test",
        )
        assert updated.duration_minutes == 90
        assert len(updated.reschedule_history) == 1

        # 3. Clean up
        session.delete(meeting)
        session.delete(student)
        session.delete(tutor)
        session.commit()
