from __future__ import annotations

import time
from collections.abc import Callable

import redis.asyncio as redis
from fastapi import Request

from app.config import get_settings
from app.exceptions import RateLimitError

settings = get_settings()

_redis: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


def _parse_limit(spec: str) -> tuple[int, int]:
    """Parse '10/minute' into (max_requests, window_seconds)."""
    count_str, period = spec.strip().lower().split("/")
    count = int(count_str)
    windows = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
    if period not in windows:
        raise ValueError(f"Unsupported rate limit period: {period}")
    return count, windows[period]


def rate_limit(limit_spec: str, *, key_prefix: str) -> Callable:
    max_requests, window = _parse_limit(limit_spec)

    async def _dependency(request: Request) -> None:
        client_host = request.client.host if request.client else "unknown"
        key = f"rl:{key_prefix}:{client_host}"
        try:
            r = await get_redis()
            now = time.time()
            pipe = r.pipeline()
            pipe.zremrangebyscore(key, 0, now - window)
            pipe.zadd(key, {f"{now}:{id(request)}": now})
            pipe.zcard(key)
            pipe.expire(key, window)
            results = await pipe.execute()
            current = results[2]
            if current > max_requests:
                raise RateLimitError("Rate limit exceeded. Try again later.")
        except RateLimitError:
            raise
        except Exception:
            # Fail open if Redis is unavailable (still log in production)
            return

    return _dependency
