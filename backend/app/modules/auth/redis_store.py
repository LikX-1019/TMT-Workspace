"""Redis-backed authentication state store and its injectable contract.

This is the persistence boundary for two pieces of shared authentication
state: revoked session markers and login-failure counters. The service layer
depends on the :class:`AuthStateStore` protocol so tests can inject a fake;
production wiring always supplies :class:`RedisAuthStateStore` against a real
Redis deployment. Counters are advisory throttling state, never the sole
authentication decision.
"""

from __future__ import annotations

import hashlib
from typing import NamedTuple, Protocol
from uuid import UUID

from redis.asyncio import Redis

_REVOKED_SESSION_PREFIX = "auth:revoked-session:"
_LOGIN_USER_PREFIX = "auth:login:user:"
_LOGIN_IP_PREFIX = "auth:login:ip:"


class LoginFailureCounts(NamedTuple):
    """Current failure counters for one login attempt context."""

    username: int
    ip: int


class AuthStateStore(Protocol):
    """Shared authentication state contract (revocation + throttling)."""

    async def login_failure_counts(
        self, *, username: str, client_ip: str | None
    ) -> LoginFailureCounts: ...

    async def record_login_failure(
        self, *, username: str, client_ip: str | None, window_seconds: int
    ) -> None: ...

    async def clear_login_failures(self, *, username: str, client_ip: str | None) -> None: ...

    async def is_session_revoked(self, session_id: UUID) -> bool: ...

    async def revoke_session(self, session_id: UUID, *, ttl_seconds: int) -> None: ...


def _username_key(username: str) -> str:
    """Hash the normalized username so raw identifiers stay out of Redis keys."""

    digest = hashlib.sha256(username.encode("utf-8")).hexdigest()
    return f"{_LOGIN_USER_PREFIX}{digest}"


class RedisAuthStateStore:
    """AuthStateStore implementation backed by a real Redis deployment."""

    def __init__(self, client: Redis[str]) -> None:
        self._client = client

    async def login_failure_counts(
        self, *, username: str, client_ip: str | None
    ) -> LoginFailureCounts:
        keys = [_username_key(username)]
        if client_ip is not None:
            keys.append(f"{_LOGIN_IP_PREFIX}{client_ip}")
        values = await self._client.mget(keys)
        counts = [int(value) if value is not None else 0 for value in values]
        username_count = counts[0]
        ip_count = counts[1] if len(counts) > 1 else 0
        return LoginFailureCounts(username=username_count, ip=ip_count)

    async def record_login_failure(
        self, *, username: str, client_ip: str | None, window_seconds: int
    ) -> None:
        """Increment both counters atomically; each failure extends the window."""

        for key in (
            _username_key(username),
            *([f"{_LOGIN_IP_PREFIX}{client_ip}"] if client_ip is not None else []),
        ):
            async with self._client.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                pipe.expire(key, window_seconds)
                await pipe.execute()

    async def clear_login_failures(self, *, username: str, client_ip: str | None) -> None:
        keys = [_username_key(username)]
        if client_ip is not None:
            keys.append(f"{_LOGIN_IP_PREFIX}{client_ip}")
        await self._client.delete(*keys)

    async def is_session_revoked(self, session_id: UUID) -> bool:
        return await self._client.get(f"{_REVOKED_SESSION_PREFIX}{session_id}") is not None

    async def revoke_session(self, session_id: UUID, *, ttl_seconds: int) -> None:
        """Revoke a session for the maximum remaining access-token lifetime."""

        await self._client.set(
            f"{_REVOKED_SESSION_PREFIX}{session_id}", "1", ex=max(int(ttl_seconds), 1)
        )
