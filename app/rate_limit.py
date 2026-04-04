"""Simple in-memory rate limiter for login attempts."""

import time
from collections import defaultdict

_login_failures: dict[str, list[float]] = defaultdict(list)

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
