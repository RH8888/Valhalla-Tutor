import html
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.dependencies import SESSION_COOKIE_NAME
from app.core.rate_limit import message_limiter
from app.models.message import Conversation, Message
from app.models.user import User, UserRole
from app.services.auth_service import create_session
from app.services.message_service import (
    get_or_create_conversation,
    get_student_unread_count,
    get_tutor_unread_count,
    list_messages,
    send_message,
)
from app.services.user_service import create_student


@pytest.fixture(autouse=True)
def reset_limiters():
    message_limiter.reset()
    yield
    message_limiter.reset()


@pytest.fixture
def student2_session(db_session: Session):
    student2 = create_student(
        db=db_session,
        username="student2",
        full_name="Student Two",
        password="StudentTwoPassword123!",
        email="student2@valhalla.local",
    )
    token, s_rec = create_session(db_session, student2)
    return student2, token, s_rec


def test_student_can_send_message_to_tutor(
    client: TestClient, db_session: Session, student_session, student_user: User
):
    """1. Student can send a message to the tutor."""
    raw_token, session_rec = student_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    response = client.post(
        "/student/chat/send",
        data={"content": "Hello tutor! I have a question about math."},
        headers={"X-CSRF-Token": session_rec.csrf_token},
    )
    assert response.status_code == 200
    assert "Hello tutor! I have a question about math." in response.text

    # Verify message in database
    conv = get_or_create_conversation(db_session, student_id=student_user.id)
    messages, _ = list_messages(db_session, conv.id)
    assert len(messages) == 1
    assert messages[0].sender_id == student_user.id
    assert messages[0].content == "Hello tutor! I have a question about math."
    assert messages[0].is_read is False


def test_tutor_can_reply_to_student(
    client: TestClient, db_session: Session, tutor_session, tutor_user: User, student_user: User
):
    """2. Tutor can reply to that student."""
    conv = get_or_create_conversation(db_session, student_id=student_user.id)
    send_message(db_session, conv.id, sender=student_user, content="Student question")

    raw_token, session_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    response = client.post(
        f"/tutor/messages/{conv.id}/send",
        data={"content": "Hello! I am happy to help you with math."},
        headers={"X-CSRF-Token": session_rec.csrf_token},
    )
    assert response.status_code == 200
    assert "Hello! I am happy to help you with math." in response.text

    messages, _ = list_messages(db_session, conv.id)
    assert len(messages) == 2
    assert messages[1].sender_id == tutor_user.id
    assert messages[1].content == "Hello! I am happy to help you with math."
    assert messages[1].is_read is False


def test_student_cannot_access_another_students_conversation(
    client: TestClient, db_session: Session, student_session, student2_session
):
    """3. Student cannot access another student's conversation."""
    student1_user = student_session[1].user_id
    student2, token2, session2 = student2_session

    # Student 1 creates message in their conversation
    conv1 = get_or_create_conversation(db_session, student_id=student1_user)
    send_message(db_session, conv1.id, sender=db_session.get(User, student1_user), content="Student 1 secret")

    # Student 2 tries to access tutor endpoint for conv1 -> 403 Forbidden (require_tutor fails)
    client.cookies.set(SESSION_COOKIE_NAME, token2)
    res_tutor_route = client.get(f"/tutor/messages/student/{student1_user}")
    assert res_tutor_route.status_code == 403

    # Student 2 accessing student chat endpoint only gets student 2's own conversation
    res_chat = client.get("/student/chat")
    assert res_chat.status_code == 200
    assert "Student 1 secret" not in res_chat.text

    # Student 2 cannot send a message to Student 1's conversation via service
    with pytest.raises(Exception):
        send_message(db_session, conv1.id, sender=student2, content="Unauthorized message")


def test_tutor_can_access_correct_student_conversations(
    client: TestClient, db_session: Session, tutor_session, student_user: User, student2_session
):
    """4. Tutor can access the correct student conversations."""
    student2, _, _ = student2_session
    conv1 = get_or_create_conversation(db_session, student_id=student_user.id)
    conv2 = get_or_create_conversation(db_session, student_id=student2.id)

    send_message(db_session, conv1.id, sender=student_user, content="Msg from student 1")
    send_message(db_session, conv2.id, sender=student2, content="Msg from student 2")

    raw_token, _ = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    # Inbox loads conversations
    res_inbox = client.get("/tutor/messages")
    assert res_inbox.status_code == 200
    assert student_user.full_name in res_inbox.text
    assert student2.full_name in res_inbox.text

    # Tutor accesses student 1 conversation
    res_s1 = client.get(f"/tutor/messages/student/{student_user.id}")
    assert res_s1.status_code == 200
    assert "Msg from student 1" in res_s1.text
    assert "Msg from student 2" not in res_s1.text

    # Tutor accesses student 2 conversation
    res_s2 = client.get(f"/tutor/messages/student/{student2.id}")
    assert res_s2.status_code == 200
    assert "Msg from student 2" in res_s2.text
    assert "Msg from student 1" not in res_s2.text


def test_unread_counts_and_read_receipts(
    client: TestClient, db_session: Session, tutor_session, student_session, student_user: User, tutor_user: User
):
    """5. Unread counts and read receipts work correctly."""
    tutor_token, tutor_rec = tutor_session
    student_token, student_rec = student_session

    conv = get_or_create_conversation(db_session, student_id=student_user.id)

    # Initially 0 unread
    assert get_tutor_unread_count(db_session) == 0
    assert get_student_unread_count(db_session, student_user.id) == 0

    # Student sends a message
    msg = send_message(db_session, conv.id, sender=student_user, content="Student asks something")
    assert msg.is_read is False
    assert get_tutor_unread_count(db_session) == 1
    assert get_student_unread_count(db_session, student_user.id) == 0

    # Background unread-count check does NOT mark message as read
    client.cookies.set(SESSION_COOKIE_NAME, tutor_token)
    badge_res = client.get("/tutor/messages/unread-count")
    assert badge_res.status_code == 200
    assert "1" in badge_res.text
    db_session.refresh(msg)
    assert msg.is_read is False

    # Tutor opens student conversation -> marks as read
    res_open = client.get(f"/tutor/messages/student/{student_user.id}")
    assert res_open.status_code == 200
    db_session.refresh(msg)
    assert msg.is_read is True
    assert msg.read_at is not None
    assert get_tutor_unread_count(db_session) == 0

    # Tutor replies
    reply = send_message(db_session, conv.id, sender=tutor_user, content="Tutor answers")
    assert reply.is_read is False
    assert get_student_unread_count(db_session, student_user.id) == 1

    # Student opens chat -> marks tutor message as read
    client.cookies.set(SESSION_COOKIE_NAME, student_token)
    res_chat = client.get("/student/chat")
    assert res_chat.status_code == 200
    db_session.refresh(reply)
    assert reply.is_read is True
    assert reply.read_at is not None
    assert get_student_unread_count(db_session, student_user.id) == 0


def test_empty_and_oversized_messages_are_rejected(
    client: TestClient, db_session: Session, student_session, student_user: User
):
    """6. Empty and oversized messages are rejected."""
    student_token, student_rec = student_session
    client.cookies.set(SESSION_COOKIE_NAME, student_token)

    # Empty message
    res_empty = client.post(
        "/student/chat/send",
        data={"content": "   "},
        headers={"X-CSRF-Token": student_rec.csrf_token},
    )
    assert res_empty.status_code == 422
    assert "empty" in res_empty.json()["detail"].lower()

    # Oversized message (> 5000 chars)
    oversized_content = "a" * 5001
    res_oversized = client.post(
        "/student/chat/send",
        data={"content": oversized_content},
        headers={"X-CSRF-Token": student_rec.csrf_token},
    )
    assert res_oversized.status_code == 422
    assert "5,000" in res_oversized.json()["detail"]


def test_message_content_is_safely_escaped(
    client: TestClient, db_session: Session, student_session, student_user: User
):
    """7. Message content is safely escaped against XSS."""
    student_token, student_rec = student_session
    client.cookies.set(SESSION_COOKIE_NAME, student_token)

    xss_payload = "<script>alert('pwned')</script><b>Bold & dangerous</b>"
    response = client.post(
        "/student/chat/send",
        data={"content": xss_payload},
        headers={"X-CSRF-Token": student_rec.csrf_token},
    )
    assert response.status_code == 200
    # Must NOT contain raw script tag; must be escaped
    assert "<script>alert" not in response.text
    assert "&lt;script&gt;alert" in response.text
    assert "&amp; dangerous" in response.text or "&amp;amp;" in response.text or "&amp;" in response.text


def test_authentication_and_csrf_protection_are_respected(
    client: TestClient, student_session, tutor_session
):
    """8. Existing authentication and CSRF protection are respected."""
    student_token, student_rec = student_session

    # Unauthenticated student chat access -> 401
    client.cookies.clear()
    res_unauth = client.get("/student/chat")
    assert res_unauth.status_code == 401

    # POST without CSRF token -> 403
    client.cookies.set(SESSION_COOKIE_NAME, student_token)
    res_no_csrf = client.post("/student/chat/send", data={"content": "Hello"})
    assert res_no_csrf.status_code == 403

    # POST with invalid CSRF token -> 403
    res_bad_csrf = client.post(
        "/student/chat/send",
        data={"content": "Hello"},
        headers={"X-CSRF-Token": "bad-token"},
    )
    assert res_bad_csrf.status_code == 403


def test_pagination_and_polling(
    client: TestClient, db_session: Session, tutor_session, student_session, student_user: User, tutor_user: User
):
    """Verify loading older messages and polling for new messages without duplicates."""
    student_token, student_rec = student_session
    tutor_token, tutor_rec = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, student_token)

    conv = get_or_create_conversation(db_session, student_id=student_user.id)

    # Send 5 messages
    for i in range(5):
        send_message(db_session, conv.id, sender=student_user, content=f"Msg {i}")

    # Polling with no newer messages -> 204
    messages, _ = list_messages(db_session, conv.id)
    latest_ts = messages[-1].created_at.isoformat()
    poll_res = client.get(f"/student/chat/poll?after={latest_ts}")
    assert poll_res.status_code == 204

    # Tutor replies
    tutor_msg = send_message(db_session, conv.id, sender=tutor_user, content="Tutor newest reply")

    # Polling with after=latest_ts returns the tutor's newest reply
    poll_res2 = client.get(f"/student/chat/poll?after={latest_ts}")
    assert poll_res2.status_code == 200
    assert "Tutor newest reply" in poll_res2.text

    # Loading older messages prior to the last message
    older_res = client.get(f"/student/chat/older?before={tutor_msg.created_at.isoformat()}")
    assert older_res.status_code == 200
    assert "Msg 0" in older_res.text


def test_tutor_search_conversations(
    client: TestClient, db_session: Session, tutor_session, student_user: User, student2_session
):
    """Verify tutor search by student name or username."""
    student2, _, _ = student2_session
    conv1 = get_or_create_conversation(db_session, student_id=student_user.id)
    conv2 = get_or_create_conversation(db_session, student_id=student2.id)

    send_message(db_session, conv1.id, sender=student_user, content="Alpha message")
    send_message(db_session, conv2.id, sender=student2, content="Beta message")

    tutor_token, _ = tutor_session
    client.cookies.set(SESSION_COOKIE_NAME, tutor_token)

    # Search for student 1's username
    res1 = client.get(f"/tutor/messages/conversations?q={student_user.username}")
    assert res1.status_code == 200
    assert student_user.full_name in res1.text
    assert student2.full_name not in res1.text

    # Search for student 2's name
    res2 = client.get(f"/tutor/messages/conversations?q={student2.full_name}")
    assert res2.status_code == 200
    assert student2.full_name in res2.text
    assert student_user.full_name not in res2.text


def test_multiline_content_and_rate_limit(
    client: TestClient, db_session: Session, student_session, student_user: User
):
    """Verify multiline message preservation and rate limit enforcement."""
    student_token, student_rec = student_session
    client.cookies.set(SESSION_COOKIE_NAME, student_token)

    multiline = "Line 1\nLine 2\nLine 3"
    res = client.post(
        "/student/chat/send",
        data={"content": multiline},
        headers={"X-CSRF-Token": student_rec.csrf_token},
    )
    assert res.status_code == 200
    assert "Line 1\nLine 2\nLine 3" in res.text
    assert "whitespace-pre-wrap" in res.text

    # Rate limiting: max 30 messages in 60s
    for i in range(29):
        client.post(
            "/student/chat/send",
            data={"content": f"Spam {i}"},
            headers={"X-CSRF-Token": student_rec.csrf_token},
        )
    # The 31st message should trigger 429
    res_rate_limited = client.post(
        "/student/chat/send",
        data={"content": "Exceeding limit"},
        headers={"X-CSRF-Token": student_rec.csrf_token},
    )
    assert res_rate_limited.status_code == 429
    assert "rate limit exceeded" in res_rate_limited.json()["detail"].lower()
