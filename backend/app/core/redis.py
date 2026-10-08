"""Async Redis client management.

Redis stores authentication state (revoked sessions, login throttling
counters). The client is a process-wide singleton like the SQLAlchemy engine;
tests replace the auth state store through dependency injection, never by
disabling Redis.
"""

from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import get_settings

_redis_client: Redis[str] | None = None


def get_redis_client() -> Redis[str]:
    """Return the process-wide async Redis client."""

    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
    return _redis_client


async def close_redis() -> None:
    """Close the Redis client during application shutdown."""

    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
    _redis_client = None
