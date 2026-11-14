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

