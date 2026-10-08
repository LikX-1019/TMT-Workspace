"""Authentication and credential primitives.

Password hashing, access-token issuance/validation, refresh-token generation,
and the password policy live here as pure primitives with no HTTP or database
dependencies. Provider-specific identity logic stays out of this module when
enterprise SSO is introduced; orchestration belongs to the auth module service.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.core.exceptions import PasswordPolicyError

_password_hasher = PasswordHash.recommended()

# A real Argon2id hash of an unguessable value. Verifying candidates against it
# keeps response timing similar when the username or credential does not exist.
_DUMMY_PASSWORD_HASH = _password_hasher.hash(secrets.token_urlsafe(32))

PASSWORD_MIN_LENGTH = 12


def hash_password(password: str) -> str:
    """Hash a plaintext password with Argon2id (salt handled by the hasher)."""

    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored hash in constant time."""

    return _password_hasher.verify(password, password_hash)


def verify_dummy_password(password: str) -> bool:
    """Burn password-verification time when no real credential exists.

    Verifying against a dummy hash prevents user enumeration through timing
    differences between "unknown username" and "wrong password" responses.
    """

    return _password_hasher.verify(password, _DUMMY_PASSWORD_HASH)


def password_needs_rehash(password_hash: str) -> bool:
    """Report whether a stored hash was produced by outdated Argon2 parameters."""

    return _password_hasher.current_hasher.check_needs_rehash(password_hash)


def validate_password_policy(
    password: str,
    *,
    username: str,
    employee_no: str,
    email: str | None,
) -> None:
    """Enforce the minimum password policy.

    The policy is intentionally small: length and identity-equality checks.
    Breach checking, password history, and reset flows can be added later
    without changing this call contract.
    """

    if len(password) < PASSWORD_MIN_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at least {PASSWORD_MIN_LENGTH} characters long."
        )

    normalized_password = password.strip().lower()
    identity_values = [username.strip().lower(), employee_no.strip().lower()]
    if email is not None:
        identity_values.append(email.strip().lower())
    if normalized_password in identity_values:
        raise PasswordPolicyError(
            "Password must not equal the username, employee number, or email."
        )


def hash_refresh_token(token: str) -> str:
    """Return the stable lookup hash for a high-entropy refresh token.

    Refresh tokens are generated with ~256 bits of entropy, so a fast SHA-256
    lookup hash is sufficient and keeps database lookups deterministic. This is
    deliberately not Argon2: password hashing exists to slow offline attacks on
    low-entropy secrets, which does not apply to random opaque tokens.
    """

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_refresh_token() -> str:
    """Generate a cryptographically secure opaque refresh token."""

    return secrets.token_urlsafe(48)


def create_access_token(
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    secret_key: str,
    algorithm: str,
    ttl_minutes: int,
    now: datetime | None = None,
) -> str:
    """Issue a signed HS256 access token with the platform claim contract.

    Claims are limited to ``sub`` (user id), ``typ``, ``sid`` (session id),
    ``iat``, ``exp``, and ``jti``. Roles, permissions, and personal data are
    deliberately excluded so authorization stays server-authoritative.
    """

    issued_at = (now or datetime.now(UTC)).timestamp()
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "typ": "access",
        "sid": str(session_id),
        "iat": int(issued_at),
        "exp": int(issued_at + ttl_minutes * 60),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def decode_access_token(token: str, *, secret_key: str, algorithm: str) -> dict[str, Any]:
    """Validate signature/expiry/type and return verified claims.

    Raises ``jwt.PyJWTError`` subclasses for invalid input; callers translate
    failures into the generic authentication error contract.
    """

    claims: dict[str, Any] = jwt.decode(
        token,
        secret_key,
        algorithms=[algorithm],
        options={"require": ["exp", "iat", "sub", "sid", "typ", "jti"]},
    )
    if claims["typ"] != "access":
        raise jwt.InvalidTokenError("Unexpected token type.")
    return claims


def refresh_cookie_max_age_seconds(refresh_token_ttl_days: int) -> int:
    """Return the cookie lifetime, which bounds the refresh token lifetime."""

    return refresh_token_ttl_days * 24 * 60 * 60
