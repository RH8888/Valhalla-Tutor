from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
import os

from app.core.config import settings
from app.routers import (
    auth,
    health,
    student,
    student_exams,
    student_historical_exams,
    student_practice_exams,
    tutor,
    tutor_calendar,
    tutor_scheduler,
    tutor_books,
    tutor_exams,
    tutor_historical_exams,
    tutor_messages,
    tutor_plans,
    tutor_practice_exams,
    tutor_subjects,
    tutor_tracks,
    tutor_videos,
    student_chat,
)

app = FastAPI(
    title=settings.APP_NAME,
    description="Academic Planner and Tracking System for Tutor and Students",
    version="0.1.0",
    debug=settings.DEBUG,
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)

    security_headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Content-Security-Policy": (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://unpkg.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; "
            "img-src 'self' data: https:; "
            "font-src 'self' data: https:; "
            "connect-src 'self'; "
            "media-src 'self'; "
            "object-src 'none'; "
            "frame-ancestors 'self'; "
            "base-uri 'self'; "
            "form-action 'self';"
        ),
    }

    for header_name, header_value in security_headers.items():
        if header_name not in response.headers:
            response.headers[header_name] = header_value

    # HSTS: Only when HTTPS is guaranteed in production deployment
    is_production = settings.ENVIRONMENT.lower() == "production"
    is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"
    if is_production and is_https and "Strict-Transport-Security" not in response.headers:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    return response

# Include core routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(tutor.router)
app.include_router(tutor_calendar.router)
app.include_router(tutor_scheduler.router)
app.include_router(tutor_exams.router)
app.include_router(tutor_practice_exams.router)
app.include_router(tutor_historical_exams.router)
app.include_router(tutor_plans.router)
app.include_router(tutor_subjects.router)
app.include_router(tutor_tracks.router)
app.include_router(tutor_videos.router)
app.include_router(tutor_books.router)
app.include_router(tutor_messages.router)
app.include_router(student.router)
app.include_router(student_chat.router)
app.include_router(student_exams.router)
app.include_router(student_practice_exams.router)
app.include_router(student_historical_exams.router)

# Mount static assets if the directory exists
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", summary="Root index")
def root_index(request: Request):
    from app.core.dependencies import SESSION_COOKIE_NAME
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        from app.core.database import SessionLocal
        from app.models.user import UserRole
        from app.services.auth_service import get_user_and_session_by_token
        with SessionLocal() as db:
            user, session_obj = get_user_and_session_by_token(db, token)
            if user and session_obj:
                if user.role == UserRole.TUTOR:
                    return RedirectResponse(url="/tutor/students", status_code=303)
                else:
                    return RedirectResponse(url="/student/dashboard", status_code=303)
    return {
        "app": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
        "health_db": "/health/db",
    }

