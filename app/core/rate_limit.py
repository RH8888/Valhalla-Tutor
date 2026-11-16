import ipaddress
import time
from collections import defaultdict
from functools import lru_cache
from threading import Lock
from typing import Tuple

from fastapi import HTTPException, Request, status

from app.core.config import settings


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
message_limiter = LoginRateLimiter(max_requests=30, window_seconds=60)


def _clean_ip_str(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("[") and "]" in raw:
        raw = raw[1:].split("]")[0]
    elif ":" in raw and "." in raw:
        raw = raw.split(":")[0]
    return raw


@lru_cache(maxsize=32)
def _parse_trusted_proxies(trusted_proxies_str: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for item in trusted_proxies_str.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def is_trusted_proxy(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    proxies_str = getattr(settings, "TRUSTED_PROXIES", "127.0.0.1,::1,172.16.0.0/12,10.0.0.0/8")
    trusted_networks = _parse_trusted_proxies(proxies_str)
    for net in trusted_networks:
        if ip.version == net.version and ip in net:
            return True
    return False


def get_client_ip(request: Request) -> str:
    """Extract client IP, trusting forwarded headers only from configured trusted proxies."""
    raw_peer = request.client.host if request.client else "127.0.0.1"

    peer_clean = _clean_ip_str(raw_peer)
    try:
        peer_ip_obj = ipaddress.ip_address(peer_clean)
    except ValueError:
        # Non-IP peer (e.g., 'testclient' in Starlette test harness)
        return raw_peer

    # If the immediate connecting peer is NOT a trusted proxy, do not trust forwarded headers.
    if not is_trusted_proxy(peer_ip_obj):
        return str(peer_ip_obj)

    # Peer is a trusted proxy: inspect X-Forwarded-For from right to left.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        hops = [h.strip() for h in xff.split(",") if h.strip()]
        for hop in reversed(hops):
            cleaned_hop = _clean_ip_str(hop)
            try:
                hop_ip = ipaddress.ip_address(cleaned_hop)
            except ValueError:
                continue
            if not is_trusted_proxy(hop_ip):
                return str(hop_ip)

    # Check X-Real-IP if X-Forwarded-For didn't yield an untrusted client IP
    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        cleaned_real = _clean_ip_str(x_real_ip)
        try:
            real_ip = ipaddress.ip_address(cleaned_real)
            return str(real_ip)
        except ValueError:
            pass

    # If all forwarded hops were trusted proxies or headers missing, return peer IP
    return str(peer_ip_obj)


def enforce_login_rate_limit(request: Request) -> None:
    """Dependency or check that raises 429 if login rate limit is exceeded."""
    client_ip = get_client_ip(request)
    allowed, retry_after = login_limiter.check_allowed(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many login attempts. Please try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )


def enforce_message_rate_limit(key: str) -> None:
    """Raises 429 if message rate limit is exceeded for a user key."""
    allowed, retry_after = message_limiter.check_allowed(key)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Message rate limit exceeded. Please wait {retry_after} seconds before sending another message.",
            headers={"Retry-After": str(retry_after)},
        )
    message_limiter.record_attempt(key)


