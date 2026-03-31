from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict

from fastapi import Header, HTTPException, Request, status

from app.config.settings import settings


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._hits: Dict[str, Deque[datetime]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        now = datetime.now(timezone.utc)
        bucket = self._hits[key]
        cutoff = now - timedelta(seconds=window_seconds)
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


rate_limiter = InMemoryRateLimiter()


def _read_client_key(request: Request) -> str:
    client = request.client.host if request.client else "unknown"
    return f"{client}:{request.url.path}"


async def enforce_rate_limit(request: Request) -> None:
    if not settings.rate_limit_enabled:
        return
    allowed = rate_limiter.allow(
        _read_client_key(request),
        limit=settings.rate_limit_requests_per_minute,
        window_seconds=60,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limited",
                "message": "Request rate exceeded. Please retry later.",
            },
        )


async def enforce_api_key(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> None:
    if not settings.api_key:
        return
    provided_key = x_api_key
    if not provided_key and authorization and authorization.lower().startswith("bearer "):
        provided_key = authorization[7:].strip()

    if provided_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthorized", "message": "Valid API key is required."},
        )
