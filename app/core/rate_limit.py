import time
from collections import defaultdict
from threading import Lock
from typing import Tuple

from fastapi import HTTPException, Request, status


class LoginRateLimiter:
    """In-memory rate limiter tracking failed/total login attempts per key."""

    def __init__(self, max_requests: int = 5, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.attempts: dict[str, list[float]] = defaultdict(list)
        self.lock = Lock()

    def _cleanup_old(self, key: str, now: float) -> None:
        cutoff = now - self.window_seconds
        self.attempts[key] = [t for t in self.attempts[key] if t > cutoff]

    def check_allowed(self, key: str) -> Tuple[bool, int]:
        """Check if request is allowed. Returns (allowed, remaining_seconds)."""
        now = time.time()
        with self.lock:
            self._cleanup_old(key, now)
            if len(self.attempts[key]) >= self.max_requests:
                oldest = self.attempts[key][0]
                retry_after = max(1, int(self.window_seconds - (now - oldest)))
                return False, retry_after
            return True, 0

    def record_attempt(self, key: str) -> None:
        """Record an attempt timestamp."""
        now = time.time()
        with self.lock:
            self._cleanup_old(key, now)
            self.attempts[key].append(now)

    def reset(self) -> None:
        """Clear all rate limit entries (useful for testing)."""
        with self.lock:
            self.attempts.clear()


login_limiter = LoginRateLimiter(max_requests=5, window_seconds=60)


def enforce_login_rate_limit(request: Request) -> None:
    """Dependency or check that raises 429 if login rate limit is exceeded."""
    client_ip = request.client.host if request.client else "127.0.0.1"
    allowed, retry_after = login_limiter.check_allowed(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many login attempts. Please try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

