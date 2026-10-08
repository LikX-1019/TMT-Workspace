"""Unit tests for authentication security primitives."""

import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from app.core.exceptions import PasswordPolicyError
from app.core.security import (
    PASSWORD_MIN_LENGTH,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    validate_password_policy,
    verify_dummy_password,
    verify_password,
)

SECRET = "unit-test-secret"


def make_token(ttl_minutes: int = 30) -> str:
    return create_access_token(
        user_id=uuid4(),
        session_id=uuid4(),
        secret_key=SECRET,
        algorithm="HS256",
        ttl_minutes=ttl_minutes,
    )


class TestPasswordHashing:
    def test_hash_differs_from_plaintext_and_is_argon2id(self) -> None:
        hashed = hash_password("correct horse battery staple")

        assert hashed != "correct horse battery staple"
        assert hashed.startswith("$argon2id$")

    def test_correct_password_verifies_and_wrong_fails(self) -> None:
        hashed = hash_password("correct horse battery staple")

        assert verify_password("correct horse battery staple", hashed) is True
        assert verify_password("wrong password entirely!!", hashed) is False

    def test_dummy_verification_does_not_raise(self) -> None:
        assert verify_dummy_password("anything-at-all-12") is False

    def test_needs_rehash_true_for_weaker_parameters(self) -> None:
        from argon2 import PasswordHasher as Argon2PasswordHasher

        legacy = Argon2PasswordHasher(time_cost=2, memory_cost=16384)
        legacy_hash = legacy.hash("legacy parameters password")

        assert password_needs_rehash(legacy_hash) is True
        assert password_needs_rehash(hash_password("current parameters password")) is False

    def test_verification_is_constant_work_per_call(self) -> None:
        """Unknown usernames burn the same Argon2 work as wrong passwords."""

        hashed = hash_password("some password value 123")

        start = time.perf_counter()
        verify_password("definitely wrong value", hashed)
        real_verify_duration = time.perf_counter() - start

        start = time.perf_counter()
        verify_dummy_password("definitely wrong value")
        dummy_verify_duration = time.perf_counter() - start

        assert dummy_verify_duration > 0
        assert real_verify_duration > 0
        assert abs(dummy_verify_duration - real_verify_duration) < 1.0


class TestPasswordPolicy:
    def test_rejects_short_password(self) -> None:
        with pytest.raises(PasswordPolicyError, match="at least"):
            validate_password_policy("short12!", username="alice", employee_no="E001", email=None)

    def test_minimum_length_boundary(self) -> None:
        password = "a" * PASSWORD_MIN_LENGTH
        validate_password_policy(password, username="alice", employee_no="E001", email=None)

    def test_rejects_password_equal_to_username(self) -> None:
        with pytest.raises(PasswordPolicyError, match="username"):
            validate_password_policy(
                "alice.smith123", username="alice.smith123", employee_no="E001", email=None
            )

    def test_rejects_password_equal_to_employee_no(self) -> None:
        with pytest.raises(PasswordPolicyError, match="employee number"):
            validate_password_policy(
                "emp-000123456", username="alice", employee_no="emp-000123456", email=None
            )

    def test_rejects_password_equal_to_email(self) -> None:
        with pytest.raises(PasswordPolicyError, match="email"):
            validate_password_policy(
                "Alice@Example.com",
                username="alice",
                employee_no="E001",
                email="alice@example.com",
            )


class TestAccessToken:
    def test_roundtrip_returns_expected_claims(self) -> None:
        user_id, session_id = uuid4(), uuid4()
        token = create_access_token(
            user_id=user_id,
            session_id=session_id,
            secret_key=SECRET,
            algorithm="HS256",
            ttl_minutes=30,
        )

        claims = decode_access_token(token, secret_key=SECRET, algorithm="HS256")

        assert claims["sub"] == str(user_id)
        assert claims["sid"] == str(session_id)
        assert claims["typ"] == "access"
        assert claims["exp"] - claims["iat"] == 30 * 60
        assert claims["jti"]

    def test_expired_token_is_rejected(self) -> None:
        token = make_token(ttl_minutes=0)

        with pytest.raises(jwt.ExpiredSignatureError):
            decode_access_token(token, secret_key=SECRET, algorithm="HS256")

    def test_invalid_signature_is_rejected(self) -> None:
        token = make_token()

        with pytest.raises(jwt.InvalidSignatureError):
            decode_access_token(token, secret_key="other-secret", algorithm="HS256")

    def test_refresh_type_token_is_rejected(self) -> None:
        now = datetime.now(UTC)
        payload = {
            "sub": str(uuid4()),
            "typ": "refresh",
            "sid": str(uuid4()),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=30)).timestamp()),
            "jti": uuid4().hex,
        }
        token = jwt.encode(payload, SECRET, algorithm="HS256")

        with pytest.raises(jwt.InvalidTokenError):
            decode_access_token(token, secret_key=SECRET, algorithm="HS256")

    def test_token_contains_no_pii_or_authorization_data(self) -> None:
        claims = decode_access_token(make_token(), secret_key=SECRET, algorithm="HS256")

        allowed = {"sub", "typ", "sid", "iat", "exp", "jti"}
        assert allowed == set(claims)


class TestRefreshTokenMaterial:
    def test_generated_tokens_are_high_entropy_and_unique(self) -> None:
        tokens = {generate_refresh_token() for _ in range(100)}

        assert len(tokens) == 100
        assert all(len(token) >= 32 for token in tokens)

    def test_hash_is_deterministic_sha256_hex(self) -> None:
        token = generate_refresh_token()

        assert hash_refresh_token(token) == hash_refresh_token(token)
        assert len(hash_refresh_token(token)) == 64
        assert hash_refresh_token(token) != token
