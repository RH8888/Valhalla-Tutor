import uuid
from datetime import datetime
from typing import Optional, Tuple
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.security import (
    calculate_session_expiry,
    generate_csrf_token,
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)
from app.core.timezone import now_utc, to_utc
from app.models.session import UserSession
from app.models.user import User


def authenticate_user(db: Session, identifier: str, password: str) -> Optional[User]:
    """Authenticate user by username or email. Returns User if valid & active."""
    cleaned = identifier.strip()
    user = (
        db.query(User)
        .filter(or_(User.username == cleaned, User.email == cleaned))
        .first()
    )
    if not user:
        return None
    if not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_session(db: Session, user: User) -> Tuple[str, UserSession]:
    """Create a fixed 14-day server-side session. Returns (raw_token, session_record)."""
    raw_token = generate_session_token()
    token_hash = hash_session_token(raw_token)
    csrf_token = generate_csrf_token()
    created_at = now_utc()
    expires_at = calculate_session_expiry(created_at)

    session_record = UserSession(
        user_id=user.id,
        token_hash=token_hash,
        csrf_token=csrf_token,
        created_at=created_at,
        expires_at=expires_at,
        is_revoked=False,
    )
    db.add(session_record)
    db.commit()
    db.refresh(session_record)
    return raw_token, session_record


def get_user_and_session_by_token(
    db: Session, raw_token: str
) -> Tuple[Optional[User], Optional[UserSession]]:
    """Validate raw session token. Returns (User, UserSession) or (None, None)."""
    if not raw_token:
        return None, None

    token_hash = hash_session_token(raw_token)
    session_record = (
        db.query(UserSession)
        .filter(UserSession.token_hash == token_hash)
        .first()
    )
    if not session_record:
        return None, None

    if session_record.is_revoked:
        return None, None

    # Strict fixed expiration (non-rolling)
    if now_utc() >= to_utc(session_record.expires_at):
        return None, None

    user = db.query(User).filter(User.id == session_record.user_id).first()
    if not user or not user.is_active:
        return None, None

    return user, session_record


def revoke_session(db: Session, raw_token: str) -> bool:
    """Revoke a single session by its raw token."""
    if not raw_token:
        return False
    token_hash = hash_session_token(raw_token)
    session_record = (
        db.query(UserSession)
        .filter(UserSession.token_hash == token_hash)
        .first()
    )
    if not session_record:
        return False
    session_record.is_revoked = True
    db.commit()
    return True


def revoke_all_user_sessions(db: Session, user_id: uuid.UUID) -> int:
    """Revoke all active sessions for a specific user (e.g. on deactivation)."""
    rows = (
        db.query(UserSession)
        .filter(UserSession.user_id == user_id, UserSession.is_revoked.is_(False))
        .all()
    )
    for s in rows:
        s.is_revoked = True
    db.commit()
    return len(rows)
