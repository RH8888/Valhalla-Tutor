import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_session, get_current_user, require_student, verify_csrf_token
from app.core.rate_limit import enforce_message_rate_limit
from app.core.templates import templates
from app.models.session import UserSession
from app.models.user import User
from app.services.message_service import (
    MessageValidationError,
    get_or_create_conversation,
    get_student_unread_count,
    list_messages,
    mark_messages_as_read,
    send_message,
)

router = APIRouter(
    prefix="/student/chat",
    tags=["student-chat"],
    dependencies=[Depends(require_student), Depends(verify_csrf_token)],
)


@router.get("", response_class=HTMLResponse)
def get_student_chat(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    """Open the student's 1-to-1 conversation with the tutor and mark incoming messages as read."""
    conversation = get_or_create_conversation(db, student_id=current_user.id)
    # Mark messages from tutor as read
    mark_messages_as_read(db, conversation.id, reader=current_user)

    messages, has_older = list_messages(db, conversation.id, limit=50)

    return templates.TemplateResponse(
        request=request,
        name="student/chat.html",
        context={
            "conversation": conversation,
            "messages": messages,
            "has_older": has_older,
            "current_user": current_user,
            "current_session": current_session,
            "show_sender_name": False,
        },
    )


@router.post("/send", response_class=HTMLResponse)
def send_student_message(
    request: Request,
    content: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    """Send a new message to the tutor from the authenticated student."""
    enforce_message_rate_limit(f"user_{current_user.id}")

    conversation = get_or_create_conversation(db, student_id=current_user.id)
    try:
        msg = send_message(db, conversation_id=conversation.id, sender=current_user, content=content)
    except MessageValidationError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    return templates.TemplateResponse(
        request=request,
        name="messaging/message_bubble.html",
        context={
            "msg": msg,
            "current_user": current_user,
            "current_session": current_session,
            "show_sender_name": False,
        },
    )


@router.get("/poll")
def poll_student_messages(
    request: Request,
    after: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    """HTMX poll for new incoming messages after a specific timestamp."""
    if not after:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        dt_after = datetime.fromisoformat(after)
    except Exception:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    conversation = get_or_create_conversation(db, student_id=current_user.id)
    new_messages, _ = list_messages(db, conversation_id=conversation.id, after=dt_after)

    if not new_messages:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # Active viewer marks incoming messages as read
    mark_messages_as_read(db, conversation_id=conversation.id, reader=current_user)

    return templates.TemplateResponse(
        request=request,
        name="messaging/messages_batch.html",
        context={
            "messages": new_messages,
            "current_user": current_user,
            "current_session": current_session,
            "show_sender_name": False,
        },
    )


@router.get("/older", response_class=HTMLResponse)
def load_older_student_messages(
    request: Request,
    before: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    """Load older messages prior to a given timestamp."""
    try:
        dt_before = datetime.fromisoformat(before)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid before timestamp")

    conversation = get_or_create_conversation(db, student_id=current_user.id)
    older_messages, has_older = list_messages(db, conversation_id=conversation.id, limit=30, before=dt_before)

    # Build response: next load-older button (if any) followed by older messages
    btn_html = ""
    if has_older and older_messages:
        next_before = older_messages[0].created_at.isoformat()
        btn_html = f'''<div class="text-center py-2" id="load-older-wrapper">
            <button hx-get="/student/chat/older?before={next_before}"
                    hx-target="#older-messages-slot"
                    hx-swap="outerHTML"
                    class="text-xs font-medium text-indigo-600 hover:text-indigo-800 bg-white px-3 py-1.5 rounded-full border border-slate-200 shadow-2xs hover:bg-slate-50 transition">
                &uarr; Load older messages
            </button>
        </div>'''

    rendered_messages = templates.get_template("messaging/messages_batch.html").render({
        "messages": older_messages,
        "current_user": current_user,
        "current_session": current_session,
        "show_sender_name": False,
    })

    return HTMLResponse(f'<div id="older-messages-slot">{btn_html}{rendered_messages}</div>')


@router.get("/unread-count", response_class=HTMLResponse)
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return lightweight navbar badge for unread tutor messages."""
    count = get_student_unread_count(db, student_id=current_user.id)
    if count > 0:
        return HTMLResponse(
            f'<span id="student-unread-badge" hx-get="/student/chat/unread-count" hx-trigger="every 15s" hx-swap="outerHTML">'
            f'<span class="ml-1.5 inline-flex items-center px-1.5 py-0.5 rounded-full text-xs font-semibold bg-red-500 text-white">{count}</span>'
            f'</span>'
        )
    return HTMLResponse(
        '<span id="student-unread-badge" hx-get="/student/chat/unread-count" hx-trigger="every 15s" hx-swap="outerHTML"></span>'
    )
