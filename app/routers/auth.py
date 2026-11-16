from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import SESSION_COOKIE_NAME, get_current_user_and_session
from app.core.rate_limit import enforce_login_rate_limit, get_client_ip, login_limiter
from app.core.templates import templates
from app.models.user import UserRole
from app.services.auth_service import (
    authenticate_user,
    create_session,
    get_user_and_session_by_token,
    revoke_session,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
def get_login_page(request: Request, db: Session = Depends(get_db)):
    """Render login page. Redirect if already authenticated."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        user, session_rec = get_user_and_session_by_token(db, token)
        if user and session_rec:
            if user.role == UserRole.TUTOR:
                return RedirectResponse(url="/tutor/students", status_code=status.HTTP_303_SEE_OTHER)
            return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(request=request, name="auth/login.html", context={"error": None})


@router.post("/login")
def post_login(
    request: Request,
    response: Response,
    identifier: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    """Authenticate credentials, rate-limit, and establish a new 14-day session."""
    client_ip = get_client_ip(request)
    allowed, retry_after = login_limiter.check_allowed(client_ip)
    if not allowed:
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={
                "error": f"Too many failed login attempts. Please try again in {retry_after} seconds.",
                "identifier": identifier,
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    user = authenticate_user(db, identifier=identifier, password=password)
    if not user:
        login_limiter.record_attempt(client_ip)
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={"error": "Invalid username/email or password.", "identifier": identifier},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    # Prevent session fixation: generate fresh session
    raw_token, _ = create_session(db, user)

    redirect_url = "/tutor/students" if user.role == UserRole.TUTOR else "/student/dashboard"
    resp = RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)

    resp.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=14 * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=True,
        path="/",
    )
    return resp


@router.post("/logout")
def post_logout(
    request: Request,
    db: Session = Depends(get_db),
):
    """Revoke active session and delete cookie."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        revoke_session(db, token)

    resp = RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=True,
    )
    return resp
