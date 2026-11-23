from collections import deque
from threading import Lock
from time import monotonic

from fastapi import HTTPException, Request

from app.core.config import settings


_requests: deque[float] = deque()
_lock = Lock()


async def enforce_rate_limit(request: Request) -> None:
    now = monotonic()
    cutoff = now - settings.rate_limit_window_seconds
    with _lock:
        while _requests and _requests[0] <= cutoff:
            _requests.popleft()
        if len(_requests) >= settings.rate_limit_requests:
            retry_after = max(1, int(_requests[0] + settings.rate_limit_window_seconds - now))
            raise HTTPException(
                status_code=429,
                detail={"code": "rate_limit_exceeded", "message": "Too many requests"},
                headers={"Retry-After": str(retry_after)},
            )
        _requests.append(now)
