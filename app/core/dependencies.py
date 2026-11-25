import secrets
from typing import Optional, Tuple
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.session import UserSession
from app.models.user import User, UserRole
from app.services.auth_service import get_user_and_session_by_token

SESSION_COOKIE_NAME = "valhalla_session"


def get_current_user_and_session(
    request: Request, db: Session = Depends(get_db)
) -> Tuple[User, UserSession]:
    """Retrieve verified active User and UserSession from the session cookie."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    user, session_obj = get_user_and_session_by_token(db, token)
    if not user or not session_obj:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive or invalid session",
        )

    request.state.user = user
    request.state.session = session_obj
    return user, session_obj


def get_current_user(
    user_and_session: Tuple[User, UserSession] = Depends(get_current_user_and_session),
) -> User:
    """Dependency returning verified active User."""
    return user_and_session[0]


def get_current_session(
    user_and_session: Tuple[User, UserSession] = Depends(get_current_user_and_session),
) -> UserSession:
    """Dependency returning verified active UserSession."""
    return user_and_session[1]


def require_tutor(user: User = Depends(get_current_user)) -> User:
    """Dependency enforcing TUTOR role server-side."""
    if user.role != UserRole.TUTOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tutor privileges required",
        )
    return user


def require_student(user: User = Depends(get_current_user)) -> User:
    """Dependency enforcing STUDENT role server-side."""
    if user.role != UserRole.STUDENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Student privileges required",
        )
    return user


async def verify_csrf_token(
    request: Request,
    user_and_session: Tuple[User, UserSession] = Depends(get_current_user_and_session),
) -> None:
    """Validate CSRF token on unsafe HTTP methods against the active session."""
    if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return

    _, session_obj = user_and_session
    token = request.headers.get("X-CSRF-Token")
    if not token:
        # Check form data if submitted via traditional multipart/form
        content_type = request.headers.get("content-type", "")
        if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
            form = await request.form()
            token = form.get("csrf_token")

    if not token or not secrets.compare_digest(token, session_obj.csrf_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing CSRF token",
        )

