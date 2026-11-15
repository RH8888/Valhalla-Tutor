import uuid
from datetime import datetime
from typing import List, Optional, Tuple
from sqlalchemy import func, select, or_
from sqlalchemy.orm import Session, joinedload

from app.core.timezone import now_utc
from app.models.message import Conversation, Message
from app.models.user import User, UserRole


class MessageError(Exception):
    """Base exception for messaging errors."""
    pass


class ConversationNotFoundError(MessageError):
    pass


class MessageValidationError(MessageError):
    pass


class MessagePermissionError(MessageError):
    pass


def get_or_create_conversation(
    db: Session,
    student_id: uuid.UUID,
    tutor_id: Optional[uuid.UUID] = None,
    commit: bool = True,
) -> Conversation:
    """Retrieve existing conversation for student, or create a new one."""
    conv = db.execute(
        select(Conversation)
        .where(Conversation.student_id == student_id)
        .options(joinedload(Conversation.student), joinedload(Conversation.tutor))
    ).scalar_one_or_none()

    if conv:
        if tutor_id and conv.tutor_id and conv.tutor_id != tutor_id:
            raise MessagePermissionError("Conversation is owned by another tutor.")
        if tutor_id and not conv.tutor_id:
            conv.tutor_id = tutor_id
            if commit:
                db.commit()
                db.refresh(conv)
            else:
                db.flush()
        return conv

    # Verify student exists
    student = db.get(User, student_id)
    if not student or student.role != UserRole.STUDENT:
        raise ConversationNotFoundError("Student not found or invalid role")

    conv = Conversation(
        student_id=student_id,
        tutor_id=tutor_id,
        created_at=now_utc(),
        updated_at=now_utc(),
    )
    db.add(conv)
    if commit:
        db.commit()
        db.refresh(conv)
    else:
        db.flush()
    return conv


def get_conversation_by_id(
    db: Session,
    conversation_id: uuid.UUID,
    user: Optional[User] = None,
) -> Optional[Conversation]:
    """Retrieve conversation by ID with student and tutor loaded, optionally scoped to user."""
    query = (
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(joinedload(Conversation.student), joinedload(Conversation.tutor))
    )
    if user is not None:
        if user.role == UserRole.STUDENT:
            query = query.where(Conversation.student_id == user.id)
        elif user.role == UserRole.TUTOR:
            query = query.where(or_(Conversation.tutor_id == user.id, Conversation.tutor_id.is_(None)))
    return db.execute(query).scalar_one_or_none()


def get_conversation_by_student_id(db: Session, student_id: uuid.UUID) -> Optional[Conversation]:
    """Retrieve conversation by student ID with student and tutor loaded."""
    return db.execute(
        select(Conversation)
        .where(Conversation.student_id == student_id)
        .options(joinedload(Conversation.student), joinedload(Conversation.tutor))
    ).scalar_one_or_none()


def send_message(
    db: Session,
    conversation_id: uuid.UUID,
    sender: User,
    content: str,
    commit: bool = True,
) -> Message:
    """Validate and send a text message in the conversation."""
    content_stripped = (content or "").strip()
    if not content_stripped:
        raise MessageValidationError("Message content cannot be empty.")
    if len(content_stripped) > 5000:
        raise MessageValidationError("Message cannot exceed 5,000 characters.")

    conv = get_conversation_by_id(db, conversation_id)
    if not conv:
        raise ConversationNotFoundError("Conversation does not exist.")

    # Authorization check
    if sender.role == UserRole.STUDENT and sender.id != conv.student_id:
        raise MessagePermissionError("Students cannot send messages to other conversations.")

    if sender.role == UserRole.TUTOR and conv.tutor_id is not None and conv.tutor_id != sender.id:
        raise MessagePermissionError("Tutors cannot send messages to another tutor's conversation.")

    # If tutor sends message and conversation has no tutor assigned yet, assign them
    if sender.role == UserRole.TUTOR and not conv.tutor_id:
        conv.tutor_id = sender.id

    msg_now = now_utc()
    message = Message(
        conversation_id=conversation_id,
        sender_id=sender.id,
        content=content_stripped,
        is_read=False,
        created_at=msg_now,
    )
    conv.last_message_at = msg_now
    conv.updated_at = msg_now

    db.add(message)
    if commit:
        db.commit()
        db.refresh(message)
    else:
        db.flush()
    return message


def list_messages(
    db: Session,
    conversation_id: uuid.UUID,
    limit: int = 50,
    before: Optional[datetime] = None,
    after: Optional[datetime] = None,
    user: Optional[User] = None,
) -> Tuple[List[Message], bool]:
    """
    List messages in chronological order.
    Returns (messages, has_older_messages).
    """
    if user is not None:
        conv = get_conversation_by_id(db, conversation_id)
        if not conv:
            raise ConversationNotFoundError("Conversation does not exist.")
        if user.role == UserRole.STUDENT and conv.student_id != user.id:
            raise MessagePermissionError("Access denied to conversation.")
        if user.role == UserRole.TUTOR and conv.tutor_id is not None and conv.tutor_id != user.id:
            raise MessagePermissionError("Access denied to conversation.")

    query = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .options(joinedload(Message.sender))
    )

    if after:
        # Polling new messages: strictly after timestamp, chronological asc
        query = query.where(Message.created_at > after).order_by(Message.created_at.asc())
        messages = list(db.execute(query).scalars().all())
        return messages, False

    if before:
        # Paginating backwards: messages strictly before timestamp
        query = query.where(Message.created_at < before).order_by(Message.created_at.desc()).limit(limit + 1)
        res = list(db.execute(query).scalars().all())
        has_older = len(res) > limit
        messages = res[:limit]
        messages.reverse()
        return messages, has_older

    # Default initial load: get latest 'limit' messages
    query = query.order_by(Message.created_at.desc()).limit(limit + 1)
    res = list(db.execute(query).scalars().all())
    has_older = len(res) > limit
    messages = res[:limit]
    messages.reverse()
    return messages, has_older


def mark_messages_as_read(
    db: Session,
    conversation_id: uuid.UUID,
    reader: User,
) -> int:
    """Mark incoming messages in the conversation as read by the reader."""
    conv = get_conversation_by_id(db, conversation_id)
    if not conv:
        raise ConversationNotFoundError("Conversation does not exist.")
    if reader.role == UserRole.STUDENT and conv.student_id != reader.id:
        raise MessagePermissionError("Access denied to conversation.")
    if reader.role == UserRole.TUTOR and conv.tutor_id is not None and conv.tutor_id != reader.id:
        raise MessagePermissionError("Access denied to conversation.")

    read_now = now_utc()
    stmt = (
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.sender_id != reader.id,
            Message.is_read.is_(False),
        )
    )
    unread_messages = list(db.execute(stmt).scalars().all())
    count = 0
    for m in unread_messages:
        m.is_read = True
        m.read_at = read_now
        count += 1
    if count > 0:
        db.commit()
    return count


def get_student_unread_count(db: Session, student_id: uuid.UUID) -> int:
    """Return count of unread tutor messages for this student."""
    conv = db.execute(
        select(Conversation.id).where(Conversation.student_id == student_id)
    ).scalar_one_or_none()
    if not conv:
        return 0

    count = db.execute(
        select(func.count(Message.id))
        .where(
            Message.conversation_id == conv,
            Message.sender_id != student_id,
            Message.is_read.is_(False),
        )
    ).scalar()
    return count or 0


def get_tutor_unread_count(db: Session, tutor_id: Optional[uuid.UUID] = None) -> int:
    """Return total count of unread student messages across all conversations."""
    stmt = (
        select(func.count(Message.id))
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Message.sender_id == Conversation.student_id,
            Message.is_read.is_(False),
        )
    )
    if tutor_id is not None:
        stmt = stmt.where(or_(Conversation.tutor_id == tutor_id, Conversation.tutor_id.is_(None)))
    count = db.execute(stmt).scalar()
    return count or 0


def list_tutor_conversations(
    db: Session,
    tutor_id: Optional[uuid.UUID] = None,
    search_query: Optional[str] = None,
) -> List[dict]:
    """
    List all student conversations for tutor inbox with latest message preview and unread count.
    Sorted by last_message_at DESC NULLS LAST, updated_at DESC.
    """
    query = (
        select(Conversation)
        .join(User, Conversation.student_id == User.id)
        .options(joinedload(Conversation.student))
    )
    if tutor_id is not None:
        query = query.where(or_(Conversation.tutor_id == tutor_id, Conversation.tutor_id.is_(None)))

    if search_query and search_query.strip():
        q_term = f"%{search_query.strip()}%"
        query = query.where(
            or_(
                User.full_name.ilike(q_term),
                User.username.ilike(q_term),
            )
        )

    query = query.order_by(
        Conversation.last_message_at.desc().nullslast(),
        Conversation.updated_at.desc(),
    )

    conversations = list(db.execute(query).scalars().all())
    items = []
    for conv in conversations:
        # Get latest message
        latest_msg = db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        # Unread count from this student
        unread_count = db.execute(
            select(func.count(Message.id))
            .where(
                Message.conversation_id == conv.id,
                Message.sender_id == conv.student_id,
                Message.is_read.is_(False),
            )
        ).scalar() or 0

        items.append({
            "conversation": conv,
            "student": conv.student,
            "latest_message": latest_msg,
            "unread_count": unread_count,
        })
    return items
