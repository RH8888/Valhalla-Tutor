from pathlib import Path
from app.core.rate_limit import LoginRateLimiter


def test_rate_limiter_allows_and_blocks():
    limiter = LoginRateLimiter(max_requests=3, window_seconds=10)
    key = "192.168.1.100"

    allowed, _ = limiter.check_allowed(key)
    assert allowed is True
    limiter.record_attempt(key)

    allowed, _ = limiter.check_allowed(key)
    assert allowed is True
    limiter.record_attempt(key)

    allowed, _ = limiter.check_allowed(key)
    assert allowed is True
    limiter.record_attempt(key)

    # 4th attempt should be blocked
    allowed, retry_after = limiter.check_allowed(key)
    assert allowed is False
    assert retry_after > 0

    # Different key is still allowed
    allowed_other, _ = limiter.check_allowed("192.168.1.101")
    assert allowed_other is True

    # After reset
    limiter.reset()
    allowed_reset, _ = limiter.check_allowed(key)
    assert allowed_reset is True


def test_shared_sqlite_rate_limiter_across_worker_instances(tmp_path: Path):
    db_file = str(tmp_path / "shared_limits.sqlite3")
    worker1 = LoginRateLimiter(max_requests=2, window_seconds=60, db_path=db_file, namespace="login")
    worker2 = LoginRateLimiter(max_requests=2, window_seconds=60, db_path=db_file, namespace="login")
    other_ns = LoginRateLimiter(max_requests=2, window_seconds=60, db_path=db_file, namespace="message")

    key = "203.0.113.10"
    assert worker1.check_allowed(key)[0] is True
    worker1.record_attempt(key)

    # Worker 2 sees attempt recorded by Worker 1
    assert worker2.check_allowed(key)[0] is True
    worker2.record_attempt(key)

    # Both workers now block the 3rd attempt
    allowed1, retry1 = worker1.check_allowed(key)
    allowed2, retry2 = worker2.check_allowed(key)
    assert allowed1 is False and retry1 > 0
    assert allowed2 is False and retry2 > 0

    # Separate namespace is unaffected
    assert other_ns.check_allowed(key)[0] is True

    # Resetting clears shared state for this namespace
    worker1.reset()
    assert worker2.check_allowed(key)[0] is True

