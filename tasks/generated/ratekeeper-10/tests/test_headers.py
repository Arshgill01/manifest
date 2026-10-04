from ratekeeper.clock import FakeClock
from ratekeeper.headers import rate_limit_headers
from ratekeeper.limiter import RateLimiter


def test_allowed_headers():
    rl = RateLimiter(FakeClock())
    headers = rate_limit_headers(rl.check("a", "free"), "free")
    assert headers == {"X-RateLimit-Limit": "10", "X-RateLimit-Remaining-Day": "999"}


def test_retry_after_whole_seconds():
    rl = RateLimiter(FakeClock())
    for _ in range(5):
        rl.check("a", "free")
    assert rate_limit_headers(rl.check("a", "free"), "free")["Retry-After"] == "6"


def test_retry_after_rounds_fractions_up():
    rl = RateLimiter(FakeClock())
    for _ in range(50):
        rl.check("a", "pro")
    assert rate_limit_headers(rl.check("a", "pro"), "pro")["Retry-After"] == "1"
