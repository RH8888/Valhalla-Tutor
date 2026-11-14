from datetime import datetime, timezone, timedelta
from app.core.security import (
    hash_password,
    verify_password,
    generate_session_token,
    hash_session_token,
    generate_csrf_token,
    calculate_session_expiry,
)


def test_password_hashing_and_verification():
    password = "SuperSecretPassword123!"
    hashed = hash_password(password)

    assert hashed != password
    assert hashed.startswith("$argon2id$")
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False
    assert verify_password("", hashed) is False


def test_session_token_generation_and_hashing():
    t1 = generate_session_token()
    t2 = generate_session_token()
    assert t1 != t2
    assert len(t1) >= 32

    h1 = hash_session_token(t1)
    h2 = hash_session_token(t1)
    assert h1 == h2
    assert len(h1) == 64
    assert h1 != hash_session_token(t2)


def test_csrf_token_generation():
    c1 = generate_csrf_token()
    c2 = generate_csrf_token()
    assert c1 != c2
    assert len(c1) >= 32


def test_calculate_session_expiry():
    now = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)
    expiry = calculate_session_expiry(now)
    assert expiry == now + timedelta(days=14)
    assert (expiry - now).total_seconds() == 14 * 24 * 3600

