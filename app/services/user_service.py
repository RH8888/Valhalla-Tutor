import uuid
from typing import List, Optional
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import User, UserRole
from app.services.auth_service import revoke_all_user_sessions


class UserAlreadyExistsError(Exception):
    """Raised when creating a user with duplicate username or email."""
    pass


class UserNotFoundError(Exception):
    """Raised when target user is not found."""
    pass


def list_students(db: Session, include_inactive: bool = True) -> List[User]:
    """Retrieve all students ordered by full name."""
    query = db.query(User).filter(User.role == UserRole.STUDENT)
    if not include_inactive:
        query = query.filter(User.is_active.is_(True))
    return query.order_by(User.full_name.asc()).all()


def get_student_by_id(db: Session, student_id: uuid.UUID) -> Optional[User]:
    """Get a student by UUID."""
    return (
        db.query(User)
        .filter(User.id == student_id, User.role == UserRole.STUDENT)
        .first()
    )


def create_student(
    db: Session,
    username: str,
    full_name: str,
    password: str,
    email: Optional[str] = None,
    timezone: str = "Asia/Tehran",
) -> User:
    """Create a new student account with Argon2id hashed password."""
    clean_username = username.strip().lower()
    clean_email = email.strip().lower() if email and email.strip() else None

    # Check for duplicate username
    if db.query(User).filter(User.username == clean_username).first():
        raise UserAlreadyExistsError(f"Username '{clean_username}' is already taken.")

    # Check for duplicate email if provided
    if clean_email and db.query(User).filter(User.email == clean_email).first():
        raise UserAlreadyExistsError(f"Email '{clean_email}' is already in use.")

    student = User(
        username=clean_username,
        email=clean_email,
        hashed_password=hash_password(password),
        role=UserRole.STUDENT,
        full_name=full_name.strip(),
        timezone=timezone,
        is_active=True,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def reset_student_password(
    db: Session, student_id: uuid.UUID, new_password: str
) -> User:
    """Reset student password and revoke all existing sessions."""
    student = get_student_by_id(db, student_id)
    if not student:
        raise UserNotFoundError("Student not found.")

    student.hashed_password = hash_password(new_password)
    # Revoke sessions to force re-authentication
    revoke_all_user_sessions(db, student_id)
    db.commit()
    db.refresh(student)
    return student


def set_student_active_status(
    db: Session, student_id: uuid.UUID, is_active: bool
) -> User:
    """Activate or deactivate a student account. Revokes sessions on deactivation."""
    student = get_student_by_id(db, student_id)
    if not student:
        raise UserNotFoundError("Student not found.")

    student.is_active = is_active
    if not is_active:
        revoke_all_user_sessions(db, student_id)

    db.commit()
    db.refresh(student)
    return student

