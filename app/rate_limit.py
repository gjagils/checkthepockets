"""Simple in-memory rate limiter (per process): login failures and per-bucket request limits."""

import time
from collections import defaultdict

_login_failures: dict[str, list[float]] = defaultdict(list)
_buckets: dict[tuple[str, str], list[float]] = {}

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 60


def is_rate_limited(ip: str) -> bool:
    """Returns True if this IP has exceeded the login failure threshold."""
    now = time.time()
    _login_failures[ip] = [t for t in _login_failures[ip] if now - t < WINDOW_SECONDS]
    return len(_login_failures[ip]) >= MAX_ATTEMPTS


def record_failed_attempt(ip: str) -> None:
    _login_failures[ip].append(time.time())


def clear_attempts(ip: str) -> None:
    _login_failures.pop(ip, None)


def hit(bucket: str, key: str, max_attempts: int, window_seconds: int) -> bool:
    """Count one request for (bucket, key); True when the limit is already reached.

    Every call counts, successful or not: register, forgot-password and reset-password
    are abused by volume (mail flood, account creation), not by failures. Entries older
    than the window are dropped, and empty keys are removed so memory stays bounded.
    """
    now = time.time()
    stamps = [t for t in _buckets.get((bucket, key), []) if now - t < window_seconds]
    if len(stamps) >= max_attempts:
        _buckets[(bucket, key)] = stamps
        return True
    stamps.append(now)
    _buckets[(bucket, key)] = stamps
    if len(_buckets) > 10_000:  # opportunistic sweep so one-off keys do not accumulate
        for k in [k for k, v in _buckets.items() if not v or now - v[-1] >= window_seconds]:
            _buckets.pop(k, None)
    return False
