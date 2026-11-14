from typing import Optional
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import User, UserRole


def provision_tutor(
    db: Session,
    username: str,
    password: str,
    full_name: str = "Valhalla Tutor",
    email: Optional[str] = None,
    timezone: str = "Asia/Tehran",
) -> User:
    """Securely provision the tutor account without hardcoding credentials."""
    clean_username = username.strip().lower()
    clean_email = email.strip().lower() if email and email.strip() else None

    tutor = db.query(User).filter(User.username == clean_username).first()
    if not tutor:
        tutor = db.query(User).filter(User.role == UserRole.TUTOR).first()

    if tutor:
        tutor.username = clean_username
        if clean_email:
            tutor.email = clean_email
        tutor.hashed_password = hash_password(password)
        tutor.full_name = full_name
        tutor.role = UserRole.TUTOR
        tutor.timezone = timezone
        tutor.is_active = True
    else:
        tutor = User(
            username=clean_username,
            email=clean_email,
            hashed_password=hash_password(password),
            role=UserRole.TUTOR,
            full_name=full_name,
            timezone=timezone,
            is_active=True,
        )
        db.add(tutor)

    db.commit()
    db.refresh(tutor)
    return tutor

