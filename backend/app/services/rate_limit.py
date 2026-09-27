"""Small process-local rate limiter for expensive/public endpoints."""
from collections import defaultdict, deque
from time import monotonic

from fastapi import HTTPException, Request, status


class FixedWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = monotonic()
        timestamps = self._requests[key]
        cutoff = now - self.window_seconds
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()
        if len(timestamps) >= self.limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
                headers={"Retry-After": str(self.window_seconds)},
            )
        timestamps.append(now)


def reset_rate_limiters() -> None:
    """Clear limiter state for tests and controlled process maintenance."""
    for limiter in (_auth_limiter, _upload_limiter, _copilot_limiter):
        limiter._requests.clear()


_auth_limiter = FixedWindowRateLimiter(limit=100)
_upload_limiter = FixedWindowRateLimiter(limit=30)
_copilot_limiter = FixedWindowRateLimiter(limit=60)


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def check_auth_rate_limit(request: Request) -> None:
    _auth_limiter.check(_client_key(request))


def check_upload_rate_limit(request: Request) -> None:
    _upload_limiter.check(_client_key(request))


def check_copilot_rate_limit(request: Request) -> None:
    _copilot_limiter.check(_client_key(request))
