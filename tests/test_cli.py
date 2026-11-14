from unittest.mock import patch
from sqlalchemy.orm import Session
from app.cli import main
from app.core.security import verify_password
from app.models.user import User, UserRole


def test_cli_create_tutor(db_session: Session):
    with patch("app.cli.SessionLocal", return_value=db_session):
        test_args = [
            "cli.py",
            "create-tutor",
            "--username", "cli_tutor",
            "--password", "CliSecurePass123!",
            "--name", "CLI Admin Tutor",
            "--email", "admin@valhalla.local",
            "--timezone", "Asia/Tehran",
        ]
        with patch("sys.argv", test_args):
            main()

    tutor = db_session.query(User).filter(User.username == "cli_tutor").first()
    assert tutor is not None
    assert tutor.role == UserRole.TUTOR
    assert tutor.full_name == "CLI Admin Tutor"
    assert tutor.email == "admin@valhalla.local"
    assert tutor.timezone == "Asia/Tehran"
    assert verify_password("CliSecurePass123!", tutor.hashed_password)


def test_cli_seed_academic(db_session: Session):
    with patch("app.cli.SessionLocal", return_value=db_session):
        test_args = ["cli.py", "seed-academic"]
        with patch("sys.argv", test_args):
            main()

    from app.services.academic_service import list_tracks, list_subjects
    tracks = list_tracks(db_session)
    assert len(tracks) >= 2
    subjects = list_subjects(db_session)
    assert len(subjects) >= 8


