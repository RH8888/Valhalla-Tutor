import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_session, get_current_user, require_tutor, verify_csrf_token
from app.core.rate_limit import enforce_message_rate_limit
from app.core.templates import templates
from app.models.message import Conversation
from app.models.session import UserSession
from app.models.user import User, UserRole
from app.services.message_service import (
    ConversationNotFoundError,
    MessageValidationError,
    get_conversation_by_id,
    get_or_create_conversation,
    get_tutor_unread_count,
    list_messages,
    list_tutor_conversations,
    mark_messages_as_read,
    send_message,
)
from app.services.user_service import list_students

router = APIRouter(
    prefix="/tutor/messages",
    tags=["tutor-messages"],
    dependencies=[Depends(require_tutor), Depends(verify_csrf_token)],
)


@router.get("", response_class=HTMLResponse)
def get_tutor_inbox(
    request: Request,
    student_id: Optional[uuid.UUID] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    """Tutor messaging inbox view with conversations list and active chat pane."""
    conversations = list_tutor_conversations(db, search_query=q)
    all_students = list_students(db, include_inactive=False)

    active_conv = None
    active_student = None
    messages = []
    has_older = False

    target_student_id = student_id
    if not target_student_id and conversations:
        target_student_id = conversations[0]["student"].id

    if target_student_id:
        active_student = db.get(User, target_student_id)
        if active_student and active_student.role == UserRole.STUDENT:
            active_conv = get_or_create_conversation(db, student_id=target_student_id, tutor_id=current_user.id)
            mark_messages_as_read(db, conversation_id=active_conv.id, reader=current_user)
            messages, has_older = list_messages(db, conversation_id=active_conv.id, limit=50)

    return templates.TemplateResponse(
        request=request,
        name="tutor/messages/inbox.html",
        context={
            "conversations": conversations,
            "all_students": all_students,
            "conversation": active_conv,
            "student": active_student,
            "active_student_id": target_student_id,
            "messages": messages,
            "has_older": has_older,
            "search_query": q,
            "current_user": current_user,
            "current_session": current_session,
            "show_sender_name": False,
        },
    )


@router.get("/conversations", response_class=HTMLResponse)
def get_conversations_partial(
    request: Request,
    q: Optional[str] = None,
    active_student_id: Optional[uuid.UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return HTMX partial for conversations list (used by search and auto-refresh)."""
    conversations = list_tutor_conversations(db, search_query=q)
    return templates.TemplateResponse(
        request=request,
        name="tutor/messages/partials/conversation_list.html",
        context={
            "conversations": conversations,
            "current_user": current_user,
            "active_student_id": active_student_id,
        },
    )


@router.get("/student/{student_id}", response_class=HTMLResponse)
def get_student_conversation_pane(
    student_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    """Load conversation thread pane for a specific student."""
    student = db.get(User, student_id)
    if not student or student.role != UserRole.STUDENT:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    conv = get_or_create_conversation(db, student_id=student_id, tutor_id=current_user.id)
    mark_messages_as_read(db, conversation_id=conv.id, reader=current_user)
    messages, has_older = list_messages(db, conversation_id=conv.id, limit=50)

    return templates.TemplateResponse(
        request=request,
        name="tutor/messages/partials/conversation_pane.html",
        context={
            "conversation": conv,
            "student": student,
            "messages": messages,
            "has_older": has_older,
            "current_user": current_user,
            "current_session": current_session,
            "show_sender_name": False,
        },
    )


@router.post("/{conversation_id}/send", response_class=HTMLResponse)
def send_tutor_message(
    conversation_id: uuid.UUID,
    request: Request,
    content: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    """Send a reply to the student in this conversation."""
    enforce_message_rate_limit(f"user_{current_user.id}")

    try:
        msg = send_message(db, conversation_id=conversation_id, sender=current_user, content=content)
    except MessageValidationError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except ConversationNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

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


@router.get("/{conversation_id}/poll")
def poll_tutor_messages(
    conversation_id: uuid.UUID,
    request: Request,
    after: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_session: UserSession = Depends(get_current_session),
):
    """HTMX poll for incoming messages in this conversation."""
    if not after:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        dt_after = datetime.fromisoformat(after)
    except Exception:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    new_messages, _ = list_messages(db, conversation_id=conversation_id, after=dt_after)
    if not new_messages:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    mark_messages_as_read(db, conversation_id=conversation_id, reader=current_user)

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


@router.get("/{conversation_id}/older", response_class=HTMLResponse)
def load_older_tutor_messages(
    conversation_id: uuid.UUID,
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

    older_messages, has_older = list_messages(db, conversation_id=conversation_id, limit=30, before=dt_before)

    btn_html = ""
    if has_older and older_messages:
        next_before = older_messages[0].created_at.isoformat()
        btn_html = f'''<div class="text-center py-2" id="load-older-wrapper">
            <button hx-get="/tutor/messages/{conversation_id}/older?before={next_before}"
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
def get_tutor_unread_badge(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return total unread message count badge for tutor navbar."""
    count = get_tutor_unread_count(db)
    if count > 0:
        return HTMLResponse(
            f'<span id="tutor-unread-badge" hx-get="/tutor/messages/unread-count" hx-trigger="every 15s" hx-swap="outerHTML">'
            f'<span class="ml-1.5 inline-flex items-center px-1.5 py-0.5 rounded-full text-xs font-semibold bg-red-500 text-white">{count}</span>'
            f'</span>'
        )
    return HTMLResponse(
        '<span id="tutor-unread-badge" hx-get="/tutor/messages/unread-count" hx-trigger="every 15s" hx-swap="outerHTML"></span>'
    )
