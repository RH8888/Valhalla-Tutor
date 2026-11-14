import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Tuple

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2id."""
    return _ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against an Argon2id hash."""
    try:
        return _ph.verify(hashed_password, plain_password)
    except VerificationError:
        return False
    except Exception:
        return False


def generate_session_token() -> str:
    """Generate a cryptographically secure random session token string."""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """Hash a session token with SHA-256 for secure database storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_csrf_token() -> str:
    """Generate a cryptographically secure random anti-CSRF token."""
    return secrets.token_urlsafe(32)


def calculate_session_expiry(created_at: datetime) -> datetime:
    """Calculate fixed 14-day expiration timestamp."""
    return created_at + timedelta(days=14)

